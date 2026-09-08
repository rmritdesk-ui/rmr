from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import TrainingProgress, TrainingResource, User
from ..permissions import is_global_admin, require_global_admin, require_tenant_access
from ..schemas import TrainingProgressUpdate
from ..security import current_user, require_request_origin
from ..services import audit
from ..utils import model_dict, slugify

router = APIRouter(prefix="/api", tags=["training"])


@router.get("/training")
def list_training(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if is_global_admin(user):
        resources = list(db.scalars(select(TrainingResource).order_by(TrainingResource.module, TrainingResource.title)))
        return {"resources": [model_dict(resource) for resource in resources], "administration": True}
    resources = list(db.scalars(select(TrainingResource).where(TrainingResource.published.is_(True)).order_by(TrainingResource.module, TrainingResource.title)))
    applicable = [resource for resource in resources if not resource.roles_json or user.tenant_role in resource.roles_json]
    progress_rows = list(db.scalars(select(TrainingProgress).where(
        TrainingProgress.tenant_id == user.tenant_id,
        TrainingProgress.user_id == user.id,
    )))
    progress = {row.resource_id: model_dict(row) for row in progress_rows}
    return {
        "resources": [{**model_dict(resource), "progress": progress.get(resource.id)} for resource in applicable],
        "administration": False,
    }


@router.post("/training")
async def create_training(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    module: str = Form("Platform"),
    media_type: str = Form("external_link"),
    media_url: str = Form(""),
    required: bool = Form(False),
    roles: str = Form(""),
    duration_minutes: int = Form(0),
    upload: UploadFile | None = File(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_request_origin(request)
    require_global_admin(user)
    file_path = ""
    resolved_media_type = media_type
    if upload and upload.filename:
        safe_name = f"{slugify(Path(upload.filename).stem)}-{secrets.token_hex(5)}{Path(upload.filename).suffix.lower()}"
        target = settings.data_dir / "training" / safe_name
        max_bytes = settings.max_upload_mb * 1024 * 1024
        total = 0
        with target.open("wb") as out:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"Training upload exceeds {settings.max_upload_mb} MB")
                out.write(chunk)
        file_path = str(target.relative_to(settings.data_dir))
        resolved_media_type = "uploaded_file"
    resource = TrainingResource(
        title=title,
        description=description,
        module=module,
        media_type=resolved_media_type,
        media_url=media_url,
        file_path=file_path,
        required=required,
        roles_json=[role.strip() for role in roles.split(",") if role.strip()],
        duration_minutes=duration_minutes,
        created_by=user.id,
        published=True,
    )
    db.add(resource)
    db.flush()
    audit(db, user, "training.resource.created", entity_type="training_resource", entity_id=resource.id,
          data={"module": module, "media_type": resolved_media_type})
    db.commit()
    return {"resource": model_dict(resource)}


@router.patch("/training/{resource_id}/progress")
def update_progress(resource_id: str, payload: TrainingProgressUpdate, request: Request,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_request_origin(request)
    if is_global_admin(user) or not user.tenant_id:
        raise HTTPException(status_code=403, detail="Client user access required")
    resource = db.get(TrainingResource, resource_id)
    if not resource or not resource.published:
        raise HTTPException(status_code=404, detail="Training resource not found")
    row = db.scalar(select(TrainingProgress).where(
        TrainingProgress.tenant_id == user.tenant_id,
        TrainingProgress.user_id == user.id,
        TrainingProgress.resource_id == resource_id,
    ))
    if not row:
        row = TrainingProgress(tenant_id=user.tenant_id, user_id=user.id, resource_id=resource_id)
        db.add(row)
    row.status = payload.status
    row.progress_pct = payload.progress_pct
    if payload.status == "complete":
        from datetime import datetime, timezone
        row.completed_at = datetime.now(timezone.utc)
    audit(db, user, "training.progress.updated", tenant_id=user.tenant_id, entity_type="training_resource", entity_id=resource_id,
          data={"status": payload.status, "progress_pct": payload.progress_pct})
    db.commit()
    return {"progress": model_dict(row)}
