# ATTN – Attendance Management Backend (Main Application)

ATTN Main Application is the primary backend service for the ATTN attendance system. It handles user authentication, session management, and attendance tracking logic for both students and teachers. This service replaces traditional paper attendance with a modern solution where students log in with institutional credentials and mark their attendance via mobile/web app, backed by face recognition and other verification methods on the backend.

## Features

- **Authentication via Aksis**: Users (students and teachers) log in using their university Aksis credentials. The system verifies credentials and identifies the user's role (Student or Teacher). No separate sign-up required – it integrates with existing university accounts.

- **Attendance Session Management**: Teachers can create attendance sessions for a class with a specified time window. Each session is identified by a unique ID and tied to a course name, teacher, and schedule.

- **Flexible Security Levels**: The attendance system supports multiple verification modes:
  - **No Verification (Manual)**: Simply mark attendance without additional checks.
  - **Wi-Fi Verification**: Ensures the student is on the campus/classroom Wi-Fi network when marking attendance.
  - **Face Verification**: Requires the student to submit a selfie, which is compared to their Aksis profile photo for identity verification.
  - **Wi-Fi + Face (Combined)**: Most secure option requiring both network match and face match.

- **Asynchronous Face Recognition**: The main backend works in tandem with a separate Face Verification Microservice (see below) to handle heavy image processing. Student app submissions for face verification are processed in the background, so the class isn't kept waiting.

- **Real-time Feedback**: Students receive immediate feedback if an attendance attempt is recorded as pending, accepted, or failed (e.g., "pending verification", "face mismatch", "out of Wi-Fi range"). They can also query their status at any time.

- **Teacher Controls**: Instructors can view who has marked attendance (live), manually approve or reject students in real-time, and even add or adjust records after the session (for excused absences or errors). This flexibility ensures the system can handle exceptions gracefully.

- **Data Persistence**: All attendance records are eventually stored in a PostgreSQL database for permanent record-keeping. Redis is used for fast temporary storage during live sessions, and data is periodically synchronized to the database.

- **Reporting Ready**: While the frontend would handle generating reports, the backend provides all necessary data – e.g., lists of attendees for each session, attendance history for each class – which can be used to produce Excel sheets or other reports.

## Architecture Overview

This main application is built with **FastAPI** (Python) and follows a modular, scalable architecture:

- **FastAPI Application**: Exposes RESTful endpoints under `/api/v1/` for authentication, student actions, and teacher actions. It uses Pydantic models for data validation and serialization. The interactive API docs are available via Swagger UI at `/docs` when running.

- **PostgreSQL Database**: Stores persistent data:
  - Users (students and teachers basic info),
  - Attendances (each session metadata),
  - AttendanceRecords (each student's attendance status for a session).

- **Redis Cache**: Used for:
  - **Session management**: Stores active user sessions (with TTL), enabling quick authentication checks and easy logout handling.
  - **Live attendance sessions**: Stores ongoing attendance session info and records of students marking attendance in real-time. This allows quick reads/writes (low latency) during class. A background task flushes completed sessions from Redis to Postgres for permanence.

- **Integration with Microservice**: The main app delegates face recognition tasks to a separate Face Verification Microservice. It sends images and context to the microservice's API and receives results via secure webhook callbacks. (See the "Setup" section for how to run the two services together.)

- **External Integration (Aksis)**: The system connects to the Aksis web system to authenticate users and retrieve profile data (like the student's photo and class schedule). This is done via an HTTP client that navigates the Aksis login and profile pages. (No Aksis API keys are needed – it uses the user's credentials to log in on their behalf.)

## Getting Started

**Prerequisites**: 
- Python 3.10+ (if running without Docker) and Poetry/pip for dependency management, or
- Docker & Docker Compose (recommended) for containerized deployment. 
- Aksis Credentials for testing (a valid student/teacher account) – optional: the app also provides demo users for convenience. 
- Git to clone the repositories.

### Project Structure:
```
ATTN-MainApplication/
├── app/backend/                # FastAPI app (main code)
│   ├── api/                   # API route definitions (auth, student, teacher, webhooks, etc.)
│   ├── models/                # Pydantic models for DB and Redis objects
│   ├── services/              # Business logic for students and teachers
│   ├── modules/               # Utility modules (Aksis client, face verification helper, etc.)
│   ├── db/                    # Database and cache clients (Postgres, Redis) and schema
│   ├── tasks/                 # Scheduled tasks (e.g., cron job for persistence)
│   └── main.py                # FastAPI app creation and startup/shutdown events
├── app/docker-compose.yml     # Docker compose for main app (API, Nginx, Postgres, Redis)
├── app/backend/Dockerfile     # Dockerfile for building the FastAPI backend
└── tests/                     # Unit and integration tests
```

### Installation (Local Development): 

1. **Clone the repository**:
```bash
git clone https://github.com/YourUsername/ATTN-MainApplication.git
cd ATTN-MainApplication
```

2. **Setup environment variables**: Copy or rename `app/backend/.env.test` to `.env` in the same folder (`app/backend/`), and review the settings. Key variables include: 
   - `DATABASE_URL` – connection string for Postgres. 
   - `APPLICATION_REDIS_URL` and `RATE_LIMITER_REDIS_URL` – Redis connection strings (using different DB indices). 
   - `AKSIS_LOGIN_URL`, `AKSIS_OBS_URL`, `AKSIS_LESSON_SCHEDULE_URL` – URLs for Aksis system (defaults are provided for Istanbul University's system). 
   - `FACE_VERIFIER_MICROSERVICE_URL` – the URL where the face verification microservice API will be reachable. If using Docker as below, it's set to the Docker service name (e.g., `http://api-gateway:8000`). 
   - `WEBHOOK_SECRET_KEY` – a secret string shared with the microservice to secure webhooks. You must use the same value in the microservice's .env for verification to work. 
   - `MAIN_APP_BASE_URL` – the base URL for this main API as accessible by the microservice (e.g., `http://backend-api:8000` in Docker, or an external URL/domain if applicable). This is used to construct the webhook callback URL. 
   - Auth and token settings like `SECRET_KEY` for JWT signing (should be a strong secret in production), token expiration times, etc.

3. **Install dependencies & run (without Docker)**:
   If you prefer running directly: 
   ```bash
   pip install -r app/backend/requirements.txt
   python -m uvicorn backend.main:app --reload --port 8000
   ```
   Ensure a Postgres DB and Redis are running and match your .env settings. You might need to adjust `DATABASE_URL` to point to your local DB.

   However, the recommended method is to use Docker, as described below, which will set up all components consistently.

4. **Running with Docker Compose**:
   The repository includes a Docker Compose file to run the API along with its dependencies: 
   ```bash
   cd app
   docker-compose up --build
   ```
   This will start: 
   - Postgres DB (with the schema initialized via `db/schema.sql`), 
   - Redis (for cache and broker usage), 
   - FastAPI backend (as backend-api container, served via Gunicorn/Uvicorn on port 8000),
   - Nginx (as reverse proxy on port 80 and 443 for SSL termination if certificates are provided in `app/certs`).

The FastAPI app should now be accessible at **http://localhost** (or the host IP). For example: 
- Open http://localhost/health to see a health status (`{"status": "ok", ...}`). 
- Open http://localhost/docs for the interactive API documentation (Swagger UI).

**Note**: The Docker network is named `attn_shared_network` in the compose file. This is set to allow connectivity with the face microservice if it's run separately. The compose will create this network if it doesn't exist. Ensure the face microservice is configured to use the same network (see its README below).

### Configure Microservice Connection:
By default, the main app expects the face verification microservice to be reachable at the service name `api-gateway:8000` on the Docker network. This is already set in the `.env` as `FACE_VERIFIER_MICROSERVICE_URL`. If you deploy the microservice separately or on a different host, update this URL accordingly. (For a local all-in-one setup, simply running both compose files as is will connect them.)

### Demo Mode:
If you don't have Aksis credentials or want to test quickly, you can use the built-in demo accounts:
- **Demo teacher**: usernames `demo_teacher_1` through `demo_teacher_10` (password for all is `password`).
- **Demo student**: usernames `demo_student_1` through `demo_student_10` (password `password`). 

These accounts simulate login without contacting Aksis. For demo students, an example class schedule and a placeholder profile image are used. This is great for exploring the API via Swagger UI or for development.

## Usage Guide

Once the server is running, here's a typical flow of how the system would be used:

1. **Teacher starts a session**: A teacher authenticates (e.g., via `/api/v1/auth/login`) and obtains a JWT. Using this token, the teacher calls `POST /api/v1/teacher/attendances` with details like `lesson_name`, `start_time`, `end_time`, and `security_option`. This creates a new attendance session. The response will contain the `attendance_id` (a UUID) and session info. The session is now active (until the `end_time` or until manually finished).

2. **Students mark attendance**: Students log in and similarly get a JWT. A student can discover the active session ID either if provided (QR code or displayed) or by calling `GET /api/v1/student/sessions/find?lesson_name=X&teacher_name=Y` with the course and teacher name to retrieve active sessions matching those (in case of multiple classes with similar names, it returns a list). The student then calls `POST /api/v1/student/attendances/{attendance_id}/attend`:
   - If `security_option` for the session is 3 (Face required, possibly with Wi-Fi), the student must upload a selfie image with the request (as `normal_image` file). The backend will automatically attach the student's Aksis profile photo for comparison.
   - If `security_option` is 2 (Wi-Fi), no image is needed; the backend will verify the student's network (the student's IP is passed in automatically if using the provided `get_client_ip` dependency).
   - If option 1, it's a simple check with no extra data.

3. The response will indicate the result or status. For example, in face verification mode, the student's `AttendanceRecord` will show `is_attended=false` with `fail_reason="FACE_RECOGNITION_PENDING"`, meaning they must wait for verification. In other modes, `is_attended` might be `true` immediately (for success) or `false` with a fail reason if something like Wi-Fi check failed.

4. **Face verification (asynchronous)**: If face verification was involved, the student can continue with class. In the background, the system is comparing their selfie to their profile photo:
   - The student (or client app) can poll `GET /api/v1/student/attendances/{attendance_id}/status` to check if their status has been updated. Once the face match is done, this endpoint will return their record with either `is_attended=true` (success) or `is_attended=false` with `fail_reason` indicating why (e.g., "FACE_VERIFICATION_FAILED: Faces do not match" or any other reason like spoof detected).

5. **Teacher monitors/ends session**: The teacher can retrieve the live attendance records at any time via `GET /api/v1/teacher/attendances/{attendance_id}/records` to see which students have marked attendance and their statuses. The teacher can manually accept or fail a student's attendance in a live session using:
   - `POST /api/v1/teacher/attendances/{attendance_id}/live/records/{student_id}/accept` or the corresponding `/fail` endpoint (e.g., if a student is known but face verification failed, the teacher might accept them manually).

6. **Finishing the session**: When class is over, the teacher calls `POST /api/v1/teacher/attendances/{attendance_id}/finish`. This flags the session to be closed. All remaining pending verifications will still be processed if any. The background persistence job will detect the session ended and will move all records and the session into the Postgres database (typically within a few minutes at most). After that, the session data is cleared from Redis.

7. **Historical data**: Teachers can list their past sessions via `GET /api/v1/teacher/attendances/historical` and fetch records of a particular past session with `GET /api/v1/teacher/attendances/{attendance_id}/records`. They can also retroactively add a student or change a student's status in past records (using the historical endpoints) if they have permissions – for example, to mark a student excused.

Students could similarly have an endpoint (not implemented in this version) to view their own attendance history if needed (currently, the focus is on marking attendance).

### API Documentation: 
The FastAPI server includes interactive docs at the `/docs` endpoint (Swagger UI), and a Redoc documentation at `/redoc`. These document all available endpoints, request/response models, and allow testing the endpoints (you will need to paste your JWT token into the "Authorize" dialog for protected endpoints).

## Running with the Face Verification Microservice

For full functionality, you should also run the companion **ATTN-MicroserviceBackend** service, which performs the face recognition tasks. See the README for that project (below) for setup instructions. In summary: 
- Ensure both the main app and microservice share a Docker network (`attn_shared_network` by default). 
- Set the `FACE_VERIFIER_MICROSERVICE_URL` in the main app's environment to the microservice's API endpoint (already defaulted correctly for Docker Compose usage). 
- The `WEBHOOK_SECRET_KEY` value must match in both the main app and microservice config for secure communication.

If the microservice is not running, face verification requests will fail or timeout – so for security option 3, students will remain in "pending" state and eventually be marked as failed when the session ends (since no verification came). Always start the microservice alongside the main app if you plan to use face recognition features.

## Technologies and Dependencies

- **Language**: Python 3 (AsyncIO based architecture)
- **Framework**: FastAPI (for building the REST API)
- **Auth**: JWT (PyJWT) and OAuth2 Password flow for token issuance
- **Database**: PostgreSQL (async access via `asyncpg`)
- **Cache/Queue**: Redis (async via `redis-py` and as Celery broker)
- **Scheduling**: APScheduler (AsyncIO scheduler) for periodic tasks (data persistence)
- **HTTP**: httpx for async HTTP requests (used in Aksis integration and calling microservice)
- **Other**: BeautifulSoup4 for HTML parsing (Aksis), Pydantic for data models, slowapi for rate limiting.

## Contributing

Contributions, bug fixes, and feature suggestions are welcome. If you wish to contribute: 
1. Fork the repository and create a new branch for your feature/fix. 
2. Ensure you update documentation if you change functionality, and add tests for any new logic. 
3. Submit a pull request describing your changes and the problem they solve.

For major changes, please open an issue first to discuss the proposal.

## License

(Specify license if applicable, e.g., MIT License. If this project is private or not yet licensed, you can omit this section.)