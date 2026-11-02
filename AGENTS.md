# Image Processing Studio — Instructions for Codex

## Project purpose
Build a university web application for processing computationally demanding image-processing jobs. Explain implementation steps and code to a student developing on macOS using VS Code. Work incrementally and keep the project demonstrable for a university defense.

## Requirements from university assignment (priority)
1. Limit the maximum workload of a single task (e.g. file count, file size, image dimensions/pixels, operation cost, execution duration); reject oversized requests. Enforce limits in the backend, not only the browser.
2. Report progress (percentage or named processing stage) to the client while work proceeds.
3. Allow each authenticated user to create tasks (subject to a maximum), see task status and persistent history/results, and cancel queued or running tasks. Store necessary metadata in a database.
4. Require user authentication; HTTPS earns bonus points.
5. **MOST IMPORTANT:** Demonstrate real load balancing across at least two application server instances, with a load balancer such as Nginx. Ensure background computational work can also be processed on multiple workers. Provide evidence and instructions for testing both (HTTP load balancing vs worker task distribution are distinct).
6. Bonus: When all resources are busy, queue new work; tell the user their request is queued and give a clearly labeled approximate wait estimate.
7. Bonus: Automatically scale application/worker instances within a configured hard maximum. Advanced; do not prioritize before required features.
8. Bonus: Admin dashboard showing running tasks, worker/server health and load.

## Selected product
**Image Processing Studio**: upload a batch of images, select an operation, run background processing, inspect progress, cancel tasks and download results. Target JPG, PNG, and WebP. Suggested operations: resize, recompress, format conversion, grayscale. Produce ZIP downloads for batches.

## Proposed stack
- Frontend: HTML/CSS/vanilla JavaScript (no React initially).
- Backend: Python FastAPI.
- Image processing: Pillow.
- Asynchronous job processing: Celery with Redis broker.
- Persistence: PostgreSQL (jobs, users, file and result metadata).
- Load balancer: Nginx routing requests between **two FastAPI instances**.
- Deployment: Docker Compose, with two API containers and at least two worker containers.
- Development: VS Code on macOS.

## Architecture and implementation notes
Browser -> Nginx -> API-1 / API-2 -> Redis job queue -> Worker-1 / Worker-2; PostgreSQL stores users, jobs, statuses and metadata. Shared file storage is essential because jobs may run on any worker; use a shared Docker volume for local demonstration (and sanitize filenames; isolate users' files). Celery workers consume jobs from a shared queue, but task distribution does not imply that one single task is split across workers. To demonstrate concurrency, submit multiple image batches or split large batches explicitly into smaller tasks if necessary.

Implement cooperative cancellation with a database/Redis cancellation flag checked between images or computational stages. Don't claim a worker running inside Pillow can be safely interrupted immediately. Status should correctly distinguish QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED (optionally CANCELLING). Progress can use polling first; WebSocket/SSE are optional. Design database ownership checks so one user cannot access another user's jobs or output. Handle invalid and decompression-bomb images. Set upload/body, pixel, batch, concurrency and time limits, and delete old files appropriately. Use password hashing and securely configured auth tokens/session cookies, secrets in environment variables, and no credentials in git.

## Scope / milestones
1. Repository skeleton, clear README, requirements, Docker Compose draft, and a small clean UI.
2. FastAPI upload endpoints, validation, Pillow transforms and downloadable output; prove end-to-end for one image locally.
3. PostgreSQL models, user auth, persisted job history and task limits.
4. Redis/Celery asynchronous work, percentage progress, task cancellation, multi-image batch and ZIP.
5. Nginx with two API instances, at least two workers, reproducible load balancing demonstration using logs/instance identifiers, tests.
6. Queue position/approximate wait and basic admin monitor for bonus marks.
7. Optional HTTPS, then optional bounded automatic scaling, only once the core project works.

## Working style
- First inspect repository files and existing work; do not overwrite without need.
- Use small, testable steps and show exact terminal commands for macOS / VS Code.
- At each milestone state what was implemented, how to run/test it, and how to explain it at defense.
- Write readable code, short comments, consistent API naming and basic automated tests.
- Prioritize university requirements over visual polish or optional features.
- If there's a tradeoff, choose the simplest reliable implementation that makes the main load-balancing requirement demonstrable.
- Do not claim tests passed unless actually run them.

## Initial request
Start by examining the repository, proposing the concrete directory layout, then implement milestone 1 (scaffold and a minimal working frontend/backend) without attempting every feature in one giant step. Include run commands and next steps.

## User-approved visual direction (important)
Before building the UI, read `DESIGN_SYSTEM.md` and use `theme.css` tokens as the source of truth. The user selected five colors: Neon Navy, Rose Gold, Coconut Milk, Olive Green, Potent Purple. Keep the application minimalist, refined and functional. Do not replace this palette with generic blue/purple gradients. The design references are inspiration, not required app assets. Accessibility and usability take priority over aesthetics.
