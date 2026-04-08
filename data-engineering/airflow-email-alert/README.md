# Airflow Task 실패 이메일 알림 시스템 구축

## 개요

Apache Airflow DAG 실행 중 Task 실패 시 자동으로 이메일 알림을 전송하는 시스템을 구축하였습니다.  
SMTP 서버는 AWS SES를 사용하였으며, Airflow가 Private Subnet 환경에 위치한 구조를 고려하여 NAT Gateway를 통한 egress 트래픽 구조를 구성하였습니다.

## 아키텍처

```
Airflow Task 실패
      ↓
Airflow Email Alert (SMTP)
      ↓
AWS SES SMTP Endpoint (NAT Gateway 경유)
      ↓
Email 수신
```

## 기술 스택

| 항목 | 기술 |
|------|------|
| Workflow Engine | Apache Airflow |
| Email Service | AWS SES SMTP |
| Infra | AWS EC2 (Private Subnet) |
| Network | EC2 → NAT Gateway → AWS SES |

---

## 구현 내용

### 1. AWS SES SMTP 설정

SES SMTP Credentials를 생성하여 Airflow SMTP 인증에 사용하였습니다.

### 2. Airflow SMTP 설정 (airflow.cfg)

```ini
[email]
email_backend = airflow.utils.email.send_email_smtp
email_conn_id = SES_Connection
from_email = airflow@your-domain.com

[smtp]
smtp_host = email-smtp.ap-northeast-2.amazonaws.com
smtp_port = 587
smtp_starttls = True
smtp_ssl = False
smtp_mail_from = airflow@your-domain.com
smtp_timeout = 30
smtp_retry_limit = 5
```

### 3. Airflow Connection 설정

| 항목 | 값 |
|------|------|
| Conn Id | SES_Connection |
| Conn Type | Email |
| Login | SES SMTP Username |
| Password | SES SMTP Password |

### 4. DAG 설정

```python
default_args = {
    "email": ["your-email@company.com"],
    "email_on_failure": True,
    "email_on_retry": False,
}
```

---

## 보안 설계

IAM 정책에 `aws:SourceIp` 조건을 적용하여 NAT Gateway IP에서만 SES 메일 전송이 가능하도록 제한하였습니다.

```json
{
  "Effect": "Allow",
  "Action": "ses:SendRawEmail",
  "Resource": "*",
  "Condition": {
    "IpAddress": {
      "aws:SourceIp": ["NAT_GATEWAY_IP/32"]
    }
  }
}
```

---

## 포트 설정 참고

| 포트 | 설정 |
|------|------|
| 587 | starttls=True / ssl=False |
| 465 | starttls=False / ssl=True |
