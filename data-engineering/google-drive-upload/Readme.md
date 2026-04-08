# Google Drive 데이터 업로드 자동화

## 개요

MariaDB에서 추출한 데이터를 CSV로 변환하여 Google Drive에 자동 업로드하는 스크립트입니다.  
매주 반복되는 수동 업로드 업무를 자동화하여 운영 효율을 높였습니다.

## 아키텍처

```
MariaDB
  ↓ (데이터 추출 및 CSV 변환)
각 DB 서버
  ↓ (FTP 파일 전송)
중앙 서버
  ↓ (Google Drive API)
Google Drive
```

## 기술 스택

| 항목 | 기술 |
|------|------|
| Language | Python |
| API | Google Drive API v3 |
| 인증 | Google OAuth2 / 서비스 계정 |
| 스케줄러 | Crontab (주 1회 자동 실행) |
| 파일 전송 | FTP |

---

## 주요 구현 내용

### 주차 기반 파일명 자동 생성

업로드 시점의 연도와 주차를 자동으로 계산하여 파일명에 적용합니다.

```python
now_iso = datetime.datetime.now().isocalendar()
YYYY_WW = f"{now_iso[0]}_0{now_iso[1]}" if now_iso[1] < 10 else f"{now_iso[0]}_{now_iso[1]}"
# 예시: FILE1_2026_15.csv
```

### Access Token 자동 갱신

토큰 만료 시 Refresh Token을 활용해 자동으로 재발급합니다.  
Crontab으로 자동 실행되는 환경에서 인증 오류 없이 동작하도록 설계하였습니다.

```python
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
```

### 파일 권한 설정

업로드 시 파일별로 접근 권한을 세밀하게 설정합니다.

```python
file_metadata = {
    'writersCanShare': False,           # 편집자의 권한 변경 및 공유 제한
    'copyRequiresWriterPermission': True  # 뷰어/댓글 작성자 다운로드·복사 제한
}
```

### 파일 소유권 이전

업로드 후 파일 소유권을 담당자 계정으로 자동 이전합니다.

```python
updated_permission = {
    'type': 'user',
    'role': 'owner',
    'emailAddress': 'privacy@company.com',
    'transferOwnership': True
}
```

---

## 적용 배경

매주 MariaDB에서 데이터를 추출하여 Google Drive에 수동으로 업로드하는 반복 업무가 있었습니다.  
Python과 Google Drive API를 활용해 자동화하였고, Crontab으로 스케줄을 등록하여 수동 개입 없이 매주 자동 실행되도록 구성하였습니다.

---

## 사전 준비

- Google Cloud Console에서 Drive API 활성화
- OAuth2 클라이언트 또는 서비스 계정 자격증명 발급
- `SECRET_KEY_PATH`, `DRIVE_FOLDER_ID` 환경에 맞게 설정

---

## 참고

- [Google Drive API 공식 문서](https://developers.google.com/drive/api/guides/about-sdk)
