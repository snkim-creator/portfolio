from airflow import DAG
from airflow.operators.python import PythonOperator
import subprocess
import json
import time
import csv
from datetime import datetime, timedelta
import logging

from airflow.providers.mysql.hooks.mysql import MySqlHook
import pandas as pd


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2025, 4, 1),
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
}

dag = DAG(
    "rv_tomcat_error_log",
    default_args=default_args,
    schedule_interval="0 * * * *",  # hourly
    catchup=False,
)

# CloudWatch Logs Insights query file path
QUERY_FILE_PATH = "/path/to/tomcat_query.txt"
# AWS CLI profile name
AWS_PROFILE = "your_aws_profile"
# CloudWatch log group name
LOG_GROUP_NAME = "YOUR/TOMCAT/LOG/GROUP"
# Output CSV file path
CSV_FILE_PATH = "/path/to/output/rv_tomcat_log.csv"
# ColumnStore Airflow Connection ID
COLUMNSTORE_CONN_ID = "columnstore_conn"


def start_query():
    """Execute CloudWatch Logs Insights query and return query_id"""
    with open(QUERY_FILE_PATH, "r", encoding="utf-8") as f:
        query_string = f.read().strip()

    start_query_command = [
        "aws", "logs", "start-query",
        "--log-group-name", LOG_GROUP_NAME,
        "--start-time", str(int(time.time()) - 3600),
        "--end-time", str(int(time.time())),
        "--query-string", query_string,
        "--profile", AWS_PROFILE
    ]

    result = subprocess.run(start_query_command, capture_output=True, text=True)
    try:
        query_response = json.loads(result.stdout)
        query_id = query_response.get("queryId")
        if not query_id:
            raise ValueError(f"Failed to retrieve Query ID. Response: {result.stdout}")
        return query_id
    except json.JSONDecodeError as e:
        print(f"JSON parsing error: {e}, Response: {result.stdout}")
        raise


def get_query_results_iter(query_id, batch_size=50):
    """
    Generator that fetches AWS Logs results in batches.
    Yields batch_size chunks instead of loading all results into memory.
    """
    get_results_command = [
        "aws", "logs", "get-query-results",
        "--query-id", query_id,
        "--profile", AWS_PROFILE
    ]
    next_token = None

    while True:
        params = get_results_command[:]
        if next_token:
            params.extend(["--next-token", next_token])

        result = subprocess.run(params, capture_output=True, text=True)
        query_results = json.loads(result.stdout)
        status = query_results.get("status")

        if status == "Complete":
            results = query_results.get("results", [])
            for i in range(0, len(results), batch_size):
                yield results[i:i + batch_size]
            print("Query completed!")
            break
        elif status in ["Failed", "Cancelled"]:
            raise ValueError(f"Query execution failed. Status: {status}")

        next_token = query_results.get("nextToken")
        if not next_token and status == "Running":
            print("Query running... waiting")
        elif not next_token and status != "Running":
            break


def process_and_save(**kwargs):
    """Fetch query results in batches and save to CSV"""
    query_id = kwargs["ti"].xcom_pull(task_ids="start_query_task")

    headers = ["@timestamp", "http", "data1", "trace_id", "span_id", "msg"]

    try:
        with open(CSV_FILE_PATH, "w", newline="", encoding="utf-8") as f_init:
            csv.writer(f_init).writerow(headers)
            print(f"CSV initialized: {CSV_FILE_PATH}")

        with open(CSV_FILE_PATH, "a", newline="", encoding="utf-8") as f_append:
            writer = csv.writer(f_append)
            for batch in get_query_results_iter(query_id):
                for row in batch:
                    data = {item["field"]: item["value"] for item in row}
                    writer.writerow([data.get(field, "") for field in headers])
                    f_append.flush()
        print(f"CSV export complete: {CSV_FILE_PATH}")

    except Exception as e:
        print(f"Error in process_and_save: {e}")
        raise


def insert_columnstore():
    """Load CSV data into ColumnStore after pandas type cleanup"""
    logging.info("Starting ColumnStore load")
    hook = MySqlHook.get_hook(conn_id=COLUMNSTORE_CONN_ID)
    df = pd.read_csv(CSV_FILE_PATH, sep=",")

    for col in ['http', 'data1', 'trace_id', 'span_id', 'msg']:
        df[col] = df[col].fillna('')

    conn = hook.get_conn()
    cursor = conn.cursor()

    insert_query = """
        INSERT INTO dw_schema.st_tomcat_error_log
            (created_dt, http, data1, trace_id, span_id, msg)
        VALUES (%s, %s, %s, %s, %s, %s)
    """

    values = list(df[["@timestamp", "http", "data1", "trace_id", "span_id", "msg"]]
                  .itertuples(index=False, name=None))

    cursor.executemany(insert_query, values)
    conn.commit()
    cursor.close()
    conn.close()

    logging.info(f"Inserted {len(values)} rows into ColumnStore")


start_query_task = PythonOperator(
    task_id="start_query_task",
    python_callable=start_query,
    dag=dag,
)

process_and_save_task = PythonOperator(
    task_id="process_and_save_task",
    python_callable=process_and_save,
    provide_context=True,
    dag=dag,
)

insert_columnstore_task = PythonOperator(
    task_id="insert_columnstore_task",
    python_callable=insert_columnstore,
    dag=dag,
)

start_query_task >> process_and_save_task >> insert_columnstore_task
