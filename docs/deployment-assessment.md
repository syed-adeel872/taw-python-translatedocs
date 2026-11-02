# Zero-cost deployment assessment

Assessment date: 2026-11-02.

No hosting account was created, no payment method was supplied, and no public deployment was performed.

## Constraints

- FastAPI, PostgreSQL, local upload/output storage, and in-process `BackgroundTasks` must remain part of the stack.
- Zero cost only, with no payment method or paid trial.
- Do not expose an unauthenticated public service.
- Do not expose database credentials or private documents.
- Do not create accounts or deploy without explicit authorization.

## Candidate options

| Option | Potential fit | Blocking issues |
|---|---|---|
| Render free web service plus the existing Neon database | Python web service and external PostgreSQL are supported. | Free services can sleep; the local filesystem is ephemeral; in-process jobs can be interrupted; outputs are not durable; the service would be public and unauthenticated. |
| Hugging Face Spaces free Docker plus Neon | Can run a container and reach external PostgreSQL. | Storage is ephemeral; the space is public; no authentication, rate limiting, or retention controls; Docker/Space configuration is not present. |
| Fly.io, Koyeb, or Railway free allowances | May run FastAPI containers. | Free allowances and trial terms change, may require an account or card, and still do not solve authentication, ephemeral storage, or durable jobs. |
| Vercel, Netlify, or similar serverless platforms | Can host small HTTP handlers. | No durable local filesystem, unsuitable long-running background processing, and no built-in PostgreSQL job workflow. |
| Local Uvicorn plus recorded demo | Uses the verified local workflow and Neon smoke evidence. | Does not provide a public URL; requires employer acceptance of a recorded demonstration. |

Free-tier terms are volatile and must be rechecked before any future deployment. Neon is already used for controlled development and smoke testing; it is not a production database with backup or retention guarantees.

## Verdict

A safe public deployment is **not practical** under the current zero-cost and no-authentication constraints. Even when a free host exists, the application still needs:

- Authentication and authorization.
- Rate limiting, quotas, and concurrency controls.
- CSRF protection.
- Output retention and cleanup.
- Persistent object storage for uploads and outputs.
- A durable queue or restart recovery for jobs.
- TLS through a trusted reverse proxy.
- A reviewed privacy and third-party AI data policy.

Publishing now would expose an unauthenticated service and could lose uploaded or generated files when the host restarts or sleeps.

## Employer-approved fallback

The recommended fallback is a local, recorded 60–90 second demonstration following [demo-script.md](demo-script.md). It requires no hosting account, public URL, payment method, or database credential exposure.

The employer must confirm:

1. A recorded demonstration is acceptable instead of a public deployment URL.
2. No live public service is required for submission or grading.
3. If a live deployment is required, written authorization is provided to implement the missing security controls and to use a named hosting platform.
4. Any hosting account, credit card, or paid trial required by that platform is explicitly approved; otherwise the deployment no longer meets the zero-cost rule.

Until those confirmations are provided, deployment remains **PENDING** and must not be represented as complete.
