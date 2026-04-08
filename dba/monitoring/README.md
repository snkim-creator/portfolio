# Prometheus Custom Metric - sql_exporter 메트릭 모니터링

## 개요

기존 `mysqld_exporter`에서 기본 제공하지 않는 **InnoDB Lock Wait 수**와 같은 메트릭을 Prometheus 커스텀 메트릭으로 수집하는 설정입니다.  
`sql_exporter`를 활용해 SQL 쿼리 결과를 Prometheus 메트릭으로 변환하고, Grafana 대시보드에서 시각화합니다.

## 아키텍처

```
MariaDB
  └── information_schema.innodb_lock_waits
        ↓ (SQL Query)
  sql_exporter (port 9399)
        ↓ (scrape)
  Prometheus
        ↓
  Grafana Dashboard
```

## 예시 메트릭 정보

| 항목 | 내용 |
|------|------|
| 메트릭명 | `mysql_innodb_lock_waits_current` |
| 타입 | Gauge |
| 설명 | 현재 InnoDB Lock Wait 발생 건수 |
| 수집 쿼리 | `SELECT COUNT(*) FROM information_schema.innodb_lock_waits` |

## 적용 배경

기본 `mysqld_exporter`는 Lock Wait 수를 별도 메트릭으로 제공하지 않습니다.  
Lock Wait이 급증하면 서비스 지연으로 이어지기 때문에, 실시간 모니터링 및 알람 설정이 필요했습니다.  
`sql_exporter`를 도입해 커스텀 SQL 쿼리를 메트릭으로 수집하는 방식으로 해결했습니다.

## 환경

- OS: Linux (amd64)
- MariaDB: 10.x
- sql_exporter: 0.21.0
- Prometheus / Grafana 기설치 가정

---

## 설치 및 설정

### 1. MariaDB 전용 유저 생성

```sql
CREATE USER 'sql_exporter'@'localhost' IDENTIFIED BY 'YOUR_PASSWORD';
GRANT PROCESS ON *.* TO 'sql_exporter'@'localhost';
FLUSH PRIVILEGES;
```

> `PROCESS` 권한만 부여해 최소 권한 원칙을 적용했습니다.

---

### 2. 디렉토리 생성

```bash
sudo mkdir -p /home/prometheus/sql_exporter
sudo chown -R prometheus:prometheus /home/prometheus/sql_exporter
sudo chmod 750 /home/prometheus/sql_exporter
```

---

### 3. sql_exporter 설치

```bash
# 최신 릴리즈 URL 확인
curl -s https://api.github.com/repos/burningalchemist/sql_exporter/releases/latest | grep browser_download_url

# 다운로드 (amd64 기준)
wget https://github.com/burningalchemist/sql_exporter/releases/download/0.21.0/sql_exporter-0.21.0.linux-amd64.tar.gz \
  -O /home/prometheus/sql_exporter-0.21.0.linux-amd64.tar.gz

# 압축 해제 및 이동
tar -xzf sql_exporter-*.linux-amd64.tar.gz -C /home/prometheus/sql_exporter
sudo mv /home/prometheus/sql_exporter/sql_exporter-0.21.0.linux-amd64/* /home/prometheus/sql_exporter
sudo chmod +x /home/prometheus/sql_exporter/sql_exporter

# 버전 확인
/home/prometheus/sql_exporter/sql_exporter --version
```

---

### 4. sql_exporter.yml 설정

```yaml
global:
  scrape_timeout_offset: 500ms
  min_interval: 0s
  max_connections: 3
  max_idle_connections: 3

target:
  data_source_name: 'mysql://sql_exporter:YOUR_PASSWORD@127.0.0.1:3306/'
  collectors: [mysql_lock_waits]

collectors:
  - collector_name: mysql_lock_waits
    metrics:
      - metric_name: mysql_innodb_lock_waits_current
        type: gauge
        help: Current number of InnoDB lock waits
        values: [lock_wait_count]
        query: |
          SELECT COUNT(*) AS lock_wait_count
          FROM information_schema.innodb_lock_waits;
```

> 비밀번호에 `#`이 포함된 경우 URL 인코딩(`%23`)으로 대체합니다.

---

### 5. 동작 확인

```bash
# 실행
/home/prometheus/sql_exporter/sql_exporter \
  -config.file=/home/prometheus/sql_exporter/sql_exporter.yml

# 메트릭 수집 확인
curl -s http://127.0.0.1:9399/metrics | grep mysql_innodb_lock_waits_current
```

정상 수집 시 아래와 같이 출력됩니다.

```
mysql_innodb_lock_waits_current 0
```

---

### 6. systemd 등록 (서비스 자동 시작)

```bash
sudo vi /etc/systemd/system/sql_exporter.service
```

```ini
[Unit]
Description=SQL Exporter
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/home/prometheus/sql_exporter/sql_exporter \
  -config.file=/home/prometheus/sql_exporter/sql_exporter.yml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable sql_exporter
sudo systemctl start sql_exporter
```

---

## 확장 가능한 커스텀 메트릭 예시

`sql_exporter.yml`의 `collectors` 하위에 추가하면 메트릭을 쉽게 확장할 수 있습니다.

```yaml
# 슬로우 쿼리 수 모니터링
- metric_name: mysql_slow_queries_total
  type: gauge
  help: Total number of slow queries
  values: [slow_queries]
  query: |
    SHOW GLOBAL STATUS LIKE 'Slow_queries';
```

---

## 참고

- [sql_exporter GitHub](https://github.com/burningalchemist/sql_exporter)
- [Prometheus 공식 문서](https://prometheus.io/docs/)
