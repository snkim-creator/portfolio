# MySQL → Oracle 데이터 마이그레이션 ksh 스크립트

## 개요

MySQL 데이터베이스의 데이터를 Oracle INSERT문으로 변환하는 ksh 스크립트입니다.  
Oracle 스키마가 이미 존재하는 환경에서 데이터만 마이그레이션하는 용도로 제작하였습니다.  
고객사 요청으로 제작하였으며, 약 2GB 규모의 데이터를 실제 운영 환경에서 성공적으로 마이그레이션하였습니다.

---

## 아키텍처

```
MySQL Database
      ↓ (ksh 스크립트 실행)
information_schema에서 테이블 및 컬럼 메타데이터 조회
      ↓
테이블별 데이터 추출 및 Oracle INSERT문 변환
      ↓
oracle_all_insert.sql 생성
      ↓
Oracle Database에서 sql 파일 실행
```

---

## 기술 스택

| 항목 | 기술 |
|------|------|
| Script | ksh (Korn Shell) |
| Source DB | MySQL / MariaDB |
| Target DB | Oracle DB |
| 데이터 처리 | awk |

---

## 주요 구현 내용

### 테이블 및 컬럼 메타데이터 자동 조회

`information_schema`를 활용하여 대상 DB의 전체 테이블 목록과 컬럼 정보를 자동으로 조회합니다.  
스크립트에 테이블명을 하드코딩할 필요 없이 DB 전체를 자동으로 처리합니다.

### 데이터 타입별 변환 처리

MySQL과 Oracle의 데이터 타입 차이를 자동으로 처리합니다.

| MySQL 타입 | Oracle 변환 |
|------------|------------|
| DATE | `TO_DATE('값', 'YYYY-MM-DD')` |
| DATETIME / TIMESTAMP | `TO_TIMESTAMP('값', 'YYYY-MM-DD HH24:MI:SS')` |
| BIT | `CAST(col+0 AS CHAR)` |
| 숫자형 | 그대로 삽입 |
| 문자열 | 싱글쿼터 이스케이프 처리 |

### 특수문자 및 NULL 처리

문자열 컬럼의 특수문자를 안전하게 처리하여 INSERT문 오류를 방지합니다.

```
NULL 값    → NULL
\0 (NUL)   → 공백 처리
\r (CR)    → 공백 처리
\n (LF)    → 공백 처리
\t (TAB)   → 공백 처리
' (싱글쿼터) → '' 이스케이프
```

### Batch INSERT 처리

한 번에 대량의 INSERT를 처리하면 Oracle에서 오류가 발생할 수 있습니다.  
`INSERT ALL ~ SELECT 1 FROM DUAL` 구문을 활용하여 지정된 건수(기본 500건)씩 나눠서 처리합니다.

```sql
INSERT ALL
  INTO table_name (col1, col2) VALUES (val1, val2)
  INTO table_name (col1, col2) VALUES (val1, val2)
  ...
SELECT 1 FROM DUAL;
```

---

## 사용 방법

### 1. 환경변수 설정 후 실행

```bash
MYSQL_HOST=your-host \
MYSQL_PORT=3306 \
MYSQL_USER=your-user \
MYSQL_PASS=your-password \
MYSQL_DB=your-database \
ksh mysql_to_oracle.ksh
```

### 2. 생성된 SQL 파일을 Oracle에서 실행

```bash
sqlplus user/password@oracle-host @oracle_all_insert.sql
```

---

## 주의사항

- Oracle 스키마(테이블 DDL)가 사전에 생성되어 있어야 합니다
- 접속 정보는 환경변수로 주입하여 스크립트 내 하드코딩을 방지합니다
- 대용량 데이터의 경우 `BATCH_SIZE` 조정을 권장합니다

---

## 참고

- 실제 운영 환경에서 약 2GB 규모 데이터 마이그레이션 검증 완료
- 고객사 요청으로 제작 및 납품
