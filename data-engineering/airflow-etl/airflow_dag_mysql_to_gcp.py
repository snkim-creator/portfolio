from __future__ import annotations

import os
import csv
from datetime import timedelta

import pandas as pd
import pendulum

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook
from airflow.providers.google.cloud.hooks.gcs import GCSHook


MYSQL_CONN_ID = "mysql-conn"
GCP_CONN_ID = "gcp-connection"

SOURCE_SCHEMA = "salesdata"
CONTROL_SCHEMA = "salesdata"
CONTROL_TABLE = "airflow_control"

GCS_BUCKET = "my-bucket"
GCS_BASE_PREFIX = "GCS_BIZ_ANALYST_EXEC/CASE_B"

LOCAL_TMP_DIR = "/root/airflow/data/mysql_to_gcs_csv_CASE_B"

CREATED_AT_TABLES = {"pss_code_map", "sales_channel"}

ID_TABLE_PK = {
    "product": "product_id",
    "sales_items": "id",
    "sales_items_product_map": "id",
    "rsupport_org": "id",
    "cube_sales_contract": "id",
    "cube_integrated_data": "id",
    "cube_enduser_master": "id",
    "cube_enduser_info_detail": "id",
    "cube_user": "user_seq",
    "pss_sales_contract": "id",
    "pss_integrated_data": "id",
    "pss_enduser_master": "id",
    "pss_enduser_mapping": "id",
    "pss_enduser_info_detail": "id",
    "cube_pss_license": "id",
    "exchange_rates_goal": "id",
    "exchange_rates_real": "id",
}

TABLES = list(CREATED_AT_TABLES) + list(ID_TABLE_PK.keys())

YEAR_TABLE_RULES = {
    "exchange_rates_real": {"type": "year_eq", "col": "year"},
    "cube_sales_contract": {"type": "yyyymmdd_year_range", "col": "issue_date"},
    "pss_sales_contract": {"type": "yyyymmdd_year_range", "col": "issue_date"},
}

FULL_TABLES = {"cube_integrated_data", "pss_integrated_data"}


NULL_LIKE = {"null", "none", "nan"}
BAD_DATE_LIKE = {"0000-00-00", "0000-00-00 00:00:00", "00000000"}


def normalize_nulls(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.convert_dtypes()

    for col in df.columns:
        s = df[col]
        if pd.api.types.is_string_dtype(s.dtype) or s.dtype == "object":
            ss = s.astype("string").str.strip()
            lower = ss.str.lower()

            is_null_like = lower.isin(NULL_LIKE)
            is_bad_date = ss.isin(BAD_DATE_LIKE)

            df[col] = ss.mask(is_null_like | is_bad_date, pd.NA)

    return df


def make_day_prefix_from_context(context) -> str:
    dt = context["data_interval_start"].in_timezone("Asia/Seoul")
    return f"{GCS_BASE_PREFIX}/{dt.format('YYYY')}/{dt.format('MM')}/{dt.format('DD')}"


def get_last_id(cursor, table_name: str) -> int:
    cursor.execute(
        f"SELECT last_id FROM `{CONTROL_SCHEMA}`.`{CONTROL_TABLE}` WHERE table_name = %s",
        (table_name,),
    )
    row = cursor.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def upsert_last_id(cursor, table_name: str, last_id: int):
    cursor.execute(
        f"""
        INSERT INTO `{CONTROL_SCHEMA}`.`{CONTROL_TABLE}` (table_name, last_id)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE last_id = VALUES(last_id)
        """,
        (table_name, last_id),
    )


def build_year_rule_where(dt: pendulum.DateTime, rule: dict) -> tuple[str, tuple]:
    t = rule["type"]
    col = rule["col"]

    if t == "year_eq":
        return f"WHERE `{col}` = %s", (int(dt.year),)

    if t == "yyyymmdd_year_range":
        year = int(dt.year)
        start = f"{year}0101"
        end = f"{year + 1}0101"
        return f"WHERE `{col}` >= %s AND `{col}` < %s", (start, end)

    raise ValueError(f"Unknown YEAR_TABLE_RULES type: {t}")


def fetch_header_df(conn, table: str) -> pd.DataFrame:
    """컬럼명 확보용: row 없이 컬럼만 가져옴"""
    sql = f"SELECT * FROM `{SOURCE_SCHEMA}`.`{table}` LIMIT 0"
    return pd.read_sql(sql, conn)


def write_csv(df: pd.DataFrame, local_csv: str) -> None:
    df.to_csv(
        local_csv,
        index=False,
        encoding="utf-8-sig",
        na_rep="",
        quoting=csv.QUOTE_MINIMAL,
        escapechar="\\",
    )


def run_one_table(table: str, **context):
    os.makedirs(LOCAL_TMP_DIR, exist_ok=True)
    day_prefix = make_day_prefix_from_context(context)

    hook = MySqlHook(mysql_conn_id=MYSQL_CONN_ID)
    conn = hook.get_conn()
    conn.autocommit = False

    local_csv = os.path.join(LOCAL_TMP_DIR, f"{table}.csv")
    try:
        os.remove(local_csv)
    except OSError:
        pass

    try:
        cur = conn.cursor()

        gcs = GCSHook(gcp_conn_id=GCP_CONN_ID)
        object_name = f"{day_prefix}/{table}.csv"

        # full snapshot (all rows)
        if table in FULL_TABLES:
            sql = f"SELECT DISTINCT * FROM `{SOURCE_SCHEMA}`.`{table}`"
            df = normalize_nulls(pd.read_sql(sql, conn))

            if df.empty:
                header_df = fetch_header_df(conn, table)
                write_csv(header_df, local_csv)
                gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
                return {"table": table, "mode": "full_snapshot", "rows": 0, "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

            write_csv(df, local_csv)
            gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
            return {"table": table, "mode": "full_snapshot", "rows": int(df.shape[0]), "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

        # year snapshot (current year in KST)
        if table in YEAR_TABLE_RULES:
            dt = context["data_interval_start"].in_timezone("Asia/Seoul")
            rule = YEAR_TABLE_RULES[table]
            where, params = build_year_rule_where(dt, rule)
            col = rule["col"]

            sql = (
                f"SELECT DISTINCT * FROM `{SOURCE_SCHEMA}`.`{table}` "
                f"{where} "
                f"ORDER BY `{col}` ASC"
            )
            df = normalize_nulls(pd.read_sql(sql, conn, params=params))

            if df.empty:
                header_df = fetch_header_df(conn, table)
                write_csv(header_df, local_csv)
                gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
                return {"table": table, "mode": f"year_snapshot({col})", "rows": 0, "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

            write_csv(df, local_csv)
            gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
            return {"table": table, "mode": f"year_snapshot({col})", "rows": int(df.shape[0]), "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

        # created_at 기준
        if table in CREATED_AT_TABLES:
            sql = (
                f"SELECT DISTINCT * FROM `{SOURCE_SCHEMA}`.`{table}` "
                f"WHERE `created_at` >= NOW() - INTERVAL 1 DAY "
                f"ORDER BY `created_at` ASC"
            )
            df = normalize_nulls(pd.read_sql(sql, conn))

            if df.empty:
                header_df = fetch_header_df(conn, table)
                write_csv(header_df, local_csv)
                gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
                return {"table": table, "mode": "created_at_last_1day", "rows": 0, "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

            write_csv(df, local_csv)
            gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
            return {"table": table, "mode": "created_at_last_1day", "rows": int(df.shape[0]), "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

        # id 기준
        pk_col = ID_TABLE_PK[table]
        last_id = get_last_id(cur, table)

        sql = (
            f"SELECT DISTINCT * FROM `{SOURCE_SCHEMA}`.`{table}` "
            f"WHERE `{pk_col}` > %s "
            f"ORDER BY `{pk_col}` ASC"
        )
        df = normalize_nulls(pd.read_sql(sql, conn, params=(last_id,)))

        if df.empty:
            header_df = fetch_header_df(conn, table)
            write_csv(header_df, local_csv)
            gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")
            return {"table": table, "mode": f"id({pk_col})", "rows": 0, "new_last_id": last_id, "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

        cmax = pd.to_numeric(df[pk_col], errors="coerce").max()
        new_last_id = int(cmax) if pd.notna(cmax) else last_id

        write_csv(df, local_csv)
        gcs.upload(GCS_BUCKET, object_name, local_csv, mime_type="text/csv")

        upsert_last_id(cur, table, new_last_id)
        conn.commit()

        return {"table": table, "mode": f"id({pk_col})", "rows": int(df.shape[0]),
                "new_last_id": new_last_id, "gcs_uri": f"gs://{GCS_BUCKET}/{object_name}"}

    finally:
        conn.close()
        try:
            os.remove(local_csv)
        except OSError:
            pass


with DAG(
    dag_id="salesdata_mysql_to_gcs_CASE_B",
    start_date=pendulum.datetime(2026, 2, 1, tz="Asia/Seoul"),
    schedule_interval="0 5 * * *",
    catchup=False,
    default_args={
        "owner": "data",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
        "email": ["your-email@company.com"],
        "email_on_failure": True,
    },
    max_active_runs=1,
    tags=["mysql", "gcs", "csv", "incremental"],
) as dag:

    for t in TABLES:
        PythonOperator(
            task_id=f"extract_{t}",
            python_callable=run_one_table,
            op_kwargs={"table": t},
            provide_context=True,
        )
