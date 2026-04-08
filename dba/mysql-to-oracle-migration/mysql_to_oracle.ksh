#!/bin/ksh
set -eu

# ===== Connection  ===== #
MYSQL_HOST=${MYSQL_HOST:-127.0.0.1}
MYSQL_PORT=${MYSQL_PORT:-3306}
MYSQL_USER=${MYSQL_USER:-DB User}
MYSQL_PASS="${MYSQL_PASS:-DB PW}"
MYSQL_DB="${MYSQL_DB:-DB이름}"

: ${OUTFILE:=$(pwd)/oracle_all_insert.sql}
: ${BATCH_SIZE:=500}
: ${MYSQL_BIN:=mysql}

mysql_exec() {
  ${MYSQL_BIN} -h"${MYSQL_HOST}" -P"${MYSQL_PORT}" -u"${MYSQL_USER}" -p"${MYSQL_PASS}" \
    --default-character-set=utf8mb4 \
    --batch --raw --silent --skip-column-names "${MYSQL_DB}" -e "$1"
}

get_tables() {
  mysql_exec "
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema='${MYSQL_DB}'
      AND table_type='BASE TABLE'
    ORDER BY table_name;"
}

get_columns_meta() {
  tbl="$1"
  mysql_exec "
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema='${MYSQL_DB}'
      AND table_name='${tbl}'
    ORDER BY ordinal_position;"
}

build_select_list_for_tsv() {
  tbl="$1"
  get_columns_meta "${tbl}" | awk -F'\t' '
    BEGIN { n=0; sq=sprintf("%c",39); null="__NULL__" }
    {
      col=$1; dt=tolower($2)

      if (dt=="date") {
        expr="IFNULL(DATE_FORMAT(`" col "`," sq "%Y-%m-%d" sq ")," sq null sq ")"
      } else if (dt=="datetime" || dt=="timestamp") {
        expr="IFNULL(DATE_FORMAT(`" col "`," sq "%Y-%m-%d %H:%i:%s" sq ")," sq null sq ")"
      } else if (dt=="time") {
        expr="IFNULL(DATE_FORMAT(`" col "`," sq "%H:%i:%s" sq ")," sq null sq ")"
      } else if (dt=="bit") {
        expr="IFNULL(CAST((`" col "`+0) AS CHAR)," sq null sq ")"
      } else if (dt ~ /^(tinyint|smallint|mediumint|int|bigint|decimal|numeric|float|double)$/) {
        expr="IFNULL(CAST(`" col "` AS CHAR)," sq null sq ")"
      } else {
        expr="IFNULL(" \
             "REPLACE(REPLACE(REPLACE(REPLACE(CAST(`" col "` AS CHAR)," \
             " CHAR(0), " sq sq ")," \
             " CHAR(13), " sq sq ")," \
             " CHAR(10), " sq " " sq ")," \
             " CHAR(9), " sq " " sq ")," \
             sq null sq ")"
      }

      out[++n]=expr " AS `" col "`"
    }
    END {
      for(i=1;i<=n;i++){
        printf "%s%s", out[i], (i<n?", ":"")
      }
    }'
}

main() {
  TMPDIR="$(pwd)/.ora_tmp_$$"
  mkdir -p "${TMPDIR}"

  AWK_SCRIPT="${TMPDIR}/ora_insert.awk"
  cat > "${AWK_SCRIPT}" <<'AWK'
BEGIN {
  FS="\t"
  ncol=0
  col_list=""

  while ((getline line < META) > 0) {
    split(line,a,"\t")
    ncol++
    col[ncol]=a[1]
    dt[ncol]=tolower(a[2])
    col_list = col_list (ncol==1? "" : ",") col[ncol]
  }
  close(META)
  n=0
}

function ora_quote(s) { gsub(/\047/, "\047\047", s); return "\047" s "\047" }

function fmt_value(i, v, typ) {
  typ = dt[i]
  if (v=="" || v=="__NULL__" || v=="\\N") return "NULL"

  if (typ ~ /^(tinyint|smallint|mediumint|int|bigint|decimal|numeric|float|double|bit)$/) {
    return v
  } else if (typ=="date") {
    return "TO_DATE(" ora_quote(v) ", " ora_quote("YYYY-MM-DD") ")"
  } else if (typ=="datetime" || typ=="timestamp") {
    return "TO_TIMESTAMP(" ora_quote(v) ", " ora_quote("YYYY-MM-DD HH24:MI:SS") ")"
  } else {
    return ora_quote(v)
  }
}

{
  if (n % B == 0) print "INSERT ALL"

  values=""
  for (i=1; i<=ncol; i++) {
    v = (i<=NF ? $i : "\\N")
    values = values (i==1? "" : ",") fmt_value(i, v)
  }

  print "  INTO " T " (" col_list ") VALUES (" values ")"

  n++
  if (n % B == 0) { print "SELECT 1 FROM DUAL;"; print "" }
}

END {
  if (n==0) exit
  if (n % B != 0) { print "SELECT 1 FROM DUAL;"; print "" }
}
AWK

  cat > "${OUTFILE}" <<EOF
SET DEFINE OFF;
WHENEVER SQLERROR EXIT SQL.SQLCODE;
ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD';
ALTER SESSION SET NLS_TIMESTAMP_FORMAT='YYYY-MM-DD HH24:MI:SS';

EOF

  TABLES_FILE="${TMPDIR}/tables.txt"
  get_tables > "${TABLES_FILE}"

  while IFS= read tbl; do
    [ -z "${tbl}" ] && continue

    print -- "-- ====================================================================" >> "${OUTFILE}"
    print -- "-- TABLE: ${tbl}" >> "${OUTFILE}"
    print -- "-- ====================================================================" >> "${OUTFILE}"
    print -- "" >> "${OUTFILE}"

    META_TMP="${TMPDIR}/${tbl}.meta"
    get_columns_meta "${tbl}" > "${META_TMP}"

    SELECT_LIST="$(build_select_list_for_tsv "${tbl}")"

    mysql_exec "SELECT ${SELECT_LIST} FROM \`${tbl}\`;" | \
      awk -v T="${tbl}" -v META="${META_TMP}" -v B="${BATCH_SIZE}" -f "${AWK_SCRIPT}" >> "${OUTFILE}"

  done < "${TABLES_FILE}"

  print -- "COMMIT;" >> "${OUTFILE}"

  rm -rf "${TMPDIR}"
  print -- "WROTE: ${OUTFILE}"
}

main
