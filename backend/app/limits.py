"""Обмеження першої операції. Backend завжди перевіряє їх самостійно."""

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB
MAX_BODY_BYTES = MAX_FILE_BYTES + 64 * 1024  # Запас для multipart-полів.
MAX_INPUT_PIXELS = 12_000_000
MAX_INPUT_SIDE = 12_000
MAX_OUTPUT_SIDE = 4096
MAX_CONCURRENT_RESIZES = 2  # На один процес API; спільну чергу додамо пізніше.
MAX_JOBS_PER_USER = 20
MAX_ACTIVE_JOBS_PER_USER = 2
MAX_RESULT_BYTES = 20 * 1024 * 1024
MAX_PENDING_JOBS = 100
MAX_JOB_SECONDS = 60
