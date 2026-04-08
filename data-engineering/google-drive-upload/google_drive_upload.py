import os.path
import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

now = datetime.datetime.now()
now_iso = now.isocalendar()

if now_iso[1] < 10:
    YYYY_WW = str(now_iso[0]) + "_0" + str(now_iso[1])
else:
    YYYY_WW = str(now_iso[0]) + "_" + str(now_iso[1])


SECRET_KEY = r'SECRET_KEY_PATH'
CREDS_STORE = r'/token.json'
SCOPES = ['https://www.googleapis.com/auth/drive']
DRIVE_FOLDER_ID = 'YOUR_GOOGLE_DRIVE_FOLDER_ID'
FILE1_PATH = f'/DATA/tmp/log_file1.csv'
FILE2_PATH = f'/DATA/tmp/log_file2.csv'
FILE3_PATH = f'/DATA/tmp/log_file3.csv'
refresh_token_path = r'refresh_token.txt'


def authenticate():
    creds = None

    # Access Token이 있을 시, Token 사용
    if os.path.exists(CREDS_STORE):
        creds = Credentials.from_authorized_user_file(CREDS_STORE, SCOPES)

    # Access Token이 없거나 유효하지 않을 때
    if not creds or not creds.valid:
        with open(refresh_token_path, 'r') as f:
            refresh_token = f.read().strip()

        if creds and creds.expired and creds.refresh_token:
            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id='YOUR_CLIENT_ID',
                client_secret='YOUR_CLIENT_SECRET',
                scopes=SCOPES
            )
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(SECRET_KEY, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(CREDS_STORE, "w") as token:
            token.write(creds.to_json())

    return creds


def print_files(credentials, target_folder_id):
    try:
        service = build("drive", "v3", credentials=credentials)

        files = []
        page_token = None
        response = (
            service.files()
            .list(
                q="'" + target_folder_id + "' in parents",
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
            )
            .execute()
        )

        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken", None)
        print(f"page_token: {page_token}")

    except HttpError as error:
        print(f"An error occurred: {error}")
        files = None


def upload_file(credentials, target_folder_id, file_name, mime_type, upload_file_path):
    try:
        service = build("drive", "v3", credentials=credentials)

        file_metadata = {
            'name': file_name,
            'parents': [target_folder_id],
            'writersCanShare': False,       # 편집자가 권한을 변경하고 공유할 수 없도록 설정
            'copyRequiresWriterPermission': True  # 뷰어 및 댓글 작성자 다운로드/인쇄/복사 비허용
        }

        media = MediaFileUpload(upload_file_path, mimetype=mime_type, resumable=True)

        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        file_id = file.get("id")
        print(f'File ID: {file.get("id")}')

        # 파일 권한 설정
        permissions = [
            {'type': 'user', 'role': 'writer', 'emailAddress': 'your-email@company.com'},
        ]

        for permission in permissions:
            service.permissions().create(fileId=file['id'], body=permission).execute()

        # 파일 정보 조회
        file = service.files().get(fileId=file_id, fields='permissions').execute()

        # 파일 소유권 변경
        updated_permission = {
            'type': 'user',
            'role': 'owner',
            'emailAddress': 'privacy@company.com'
        }

        permission = service.permissions().create(
            fileId=file_id,
            body=updated_permission,
            transferOwnership=True
        ).execute()

    except HttpError as error:
        print(f"An error occurred: {error}")
        file = None


if __name__ == "__main__":
    creds = authenticate()
    print_files(creds, DRIVE_FOLDER_ID)
    upload_file(creds, DRIVE_FOLDER_ID, f'FILE1_{YYYY_WW}.csv', None, FILE1_PATH)
    upload_file(creds, DRIVE_FOLDER_ID, f'FILE2_{YYYY_WW}.csv', None, FILE2_PATH)
    upload_file(creds, DRIVE_FOLDER_ID, f'FILE3_{YYYY_WW}.csv', None, FILE3_PATH)
    print("-----------------------------")
    print_files(creds, DRIVE_FOLDER_ID)
