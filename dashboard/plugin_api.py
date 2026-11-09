"""Read-only routes for the Snitchboard tab, mounted under
/api/plugins/hermes-snitchboard/. Only the health check exists so far."""

from fastapi import APIRouter

router = APIRouter()


# A plain def runs in the server's thread pool, so it never blocks the event
# loop (PRD NFR3).
@router.get("/health")
def health():
    return {"plugin": "hermes-snitchboard", "status": "ok"}
