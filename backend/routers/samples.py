import logging
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import get_db
from backend.models import (Sample, SampleShare, ProcessStep, ProcessStepType, Analysis, Attachment,
                            Substrate, Project, User, SAMPLE_TYPES)
from backend.sample_ids import next_code, piece_codes
from backend import recode
from backend.utils import save_upload, chosen_files
from backend.auth import require_login, load_sample, can_view, can_edit, can_edit_entry, is_owner, is_performer
from backend import timeline as tl
from backend.lineage import CUT_TYPE_NAME, load_sample_full, load_family, pieces_of
from backend.params import parse_date, describe
from backend.choices import DEFAULT_LOCATION, LOCATION_LIST, option_lists, remember
from backend.seed import PROCESS_STEP_TYPES
from backend.config import settings
from backend.email_utils import send_confirm_samples_email, send_declined_email, send_recoded_email
from backend.i18n import t

router = APIRouter()
log = logging.getLogger("uvicorn.error")
from backend.templating import templates


def parse_tags(text: str) -> list[str] | None:
    """Split a comma-separated tag string, dropping blanks and duplicates (case-insensitive)."""
    tags, seen = [], set()
    for t in text.split(","):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    return tags or None


async def all_tags(db: AsyncSession) -> list[str]:
    rows = (await db.execute(select(Sample.tags))).scalars()
    return sorted({t for tags in rows for t in tags or []}, key=str.lower)


def _is_image(attachment: Attachment) -> bool:
    return (attachment.mime_type or "").startswith("image/")


async def _attachments_for(db: AsyncSession, entity_type: str, entity_ids: list[int]) -> dict[int, list]:
    if not entity_ids:
        return {}
    result = await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == entity_type, Attachment.entity_id.in_(entity_ids))
        .order_by(Attachment.uploaded_at)
    )
    grouped: dict[int, list] = {eid: [] for eid in entity_ids}
    for att in result.scalars():
        grouped[att.entity_id].append(att)
    return grouped


@router.get("/", response_class=HTMLResponse)
async def list_samples(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).order_by(Sample.created_at.desc()))
    samples_list = result.scalars().all()
    by_id = {s.id: s for s in samples_list}
    parent_of = dict((await db.execute(
        select(Sample.id, ProcessStep.sample_id).join(ProcessStep, Sample.cut_step_id == ProcessStep.id)
    )).all())
    # Shown as a tree: original samples (newest first), each followed by its
    # pieces sorted by ID, pieces of pieces nested one level further.
    pieces: dict[int, list[Sample]] = {}
    for s in samples_list:
        if s.id in parent_of:
            pieces.setdefault(parent_of[s.id], []).append(s)
    rows = []

    def add(sample, ancestors):
        rows.append({"sample": sample, "depth": len(ancestors), "ancestors": ancestors,
                     "pieces": len(pieces.get(sample.id, []))})
        for piece in sorted(pieces.get(sample.id, []), key=lambda p: p.code or ""):
            add(piece, ancestors + [sample.id])

    for s in samples_list:
        if parent_of.get(s.id) not in by_id:
            add(s, [])
    return templates.TemplateResponse("samples/list.html", {
        "request": request,
        "samples": samples_list,
        "rows": rows,
        "to_confirm": [s for s in samples_list if s.owner_id == current_user.id and s.requested_by_id],
        "flash": request.session.pop("flash", None),
        "can_view": can_view,
        "current_user": current_user,
    })


async def _form_context(db: AsyncSession, request: Request, current_user, sample, editing: bool, error=None):
    return {
        "request": request,
        "sample": sample,
        "editing": editing,
        "error": error,
        "sample_types": SAMPLE_TYPES,
        "substrates": (await db.execute(select(Substrate).order_by(Substrate.material, Substrate.name))).scalars().all(),
        "projects": (await db.execute(select(Project).order_by(Project.name))).scalars().all(),
        "spec_files": await _attachments_for(db, "sample", [sample.id]) if editing else {},
        "known_tags": await all_tags(db),
        "users": (await db.execute(select(User).order_by(User.username))).scalars().all()
                 if editing and current_user.is_admin else [],
        # Who a new sample can be created for (it gets their initials), or who
        # the owner can give it to. Admins reassign with the "users" list instead.
        "researchers": await _researchers(db)
                       if not editing or (sample.owner_id == current_user.id and not current_user.is_admin) else [],
        "now_year": date.today().year,
        "current_user": current_user,
    }


def _apply_form(sample: Sample, form: dict):
    """Copy submitted fields onto the sample, dropping those its type doesn't use."""
    sample.sample_type = form["sample_type"] if form["sample_type"] in SAMPLE_TYPES else "thin_film"
    commercial = sample.sample_type == "commercial"
    collaboration = sample.sample_type == "collaboration"
    sample.label = form["label"].strip() or None
    sample.substrate_id = (None if commercial or collaboration
                           else int(form["substrate_id"]) if form["substrate_id"].isdigit() else None)
    sample.project_id = (int(form["project_id"]) if collaboration and form["project_id"].isdigit()
                              else None)
    sample.substrate_dimensions = form["substrate_dimensions"].strip() or None
    sample.film_material = form["film_material"].strip() or None if sample.sample_type == "thin_film" else None
    sample.external_id = form["external_id"].strip() or None if sample.sample_type != "thin_film" else None
    sample.supplier = form["supplier"].strip() or None if commercial else None
    sample.description = form["description"].strip() or None
    sample.tags = parse_tags(form["tags"])


async def _validate(request: Request, db: AsyncSession, sample: Sample, new_files: list[UploadFile],
                    has_spec: bool) -> str | None:
    if sample.sample_type in ("thin_film", "bulk"):
        if not sample.substrate_id or not await db.get(Substrate, sample.substrate_id):
            return t(request, "Choose the substrate from the library (add it on the Substrates tab if it's missing).")
    if sample.sample_type == "commercial":
        if not sample.description:
            return t(request, "A commercial sample needs a description.")
        if not has_spec and not any(f.filename for f in new_files):
            return t(request, "A commercial sample needs its spec sheet (PDF or photo).")
    if sample.sample_type == "collaboration":
        if not sample.project_id or not await db.get(Project, sample.project_id):
            return t(request, "Choose the project the sample belongs to (add it on the Projects tab if it's missing).")
        if not sample.description:
            return t(request, "A collaboration sample needs a description.")
    return None


def _form_fields(sample_type, label, substrate_id, project_id, substrate_dimensions, film_material,
                 external_id, supplier, description, tags) -> dict:
    return dict(sample_type=sample_type, label=label, substrate_id=substrate_id, project_id=project_id,
                substrate_dimensions=substrate_dimensions, film_material=film_material,
                external_id=external_id, supplier=supplier, description=description, tags=tags)


@router.get("/new", response_class=HTMLResponse)
async def new_sample_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = Sample(sample_type="thin_film")
    return templates.TemplateResponse(
        "samples/form.html", await _form_context(db, request, current_user, sample, editing=False))


@router.post("/new")
async def create_sample(
    request: Request,
    sample_type: str = Form("thin_film"),
    label: str = Form(""),
    substrate_id: str = Form(""),
    project_id: str = Form(""),
    substrate_dimensions: str = Form(""),
    film_material: str = Form(""),
    external_id: str = Form(""),
    supplier: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    owner_id: str = Form(""),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Create a sample, for yourself or on behalf of another researcher. It gets
    the owner's initials (a collaboration sample gets its project's code). An
    admin's goes straight to the owner; anyone else's waits for the owner to
    confirm it, and the creator gets edit access."""
    # Plain values: the retry below rolls back, which expires loaded objects.
    by_id, by_admin, username, by_name = (current_user.id, current_user.is_admin,
                                          current_user.username, current_user.display_name)
    owner = current_user
    if owner_id.isdigit() and int(owner_id) != by_id:
        owner = await db.get(User, int(owner_id))
    user_id, initials = owner.id if owner else None, owner.initials if owner else None
    owner_name, owner_email = (owner.display_name, owner.email) if owner else (None, None)
    pending = False

    def new_sample() -> Sample:
        nonlocal pending
        sample = Sample()
        _apply_form(sample, _form_fields(sample_type, label, substrate_id, project_id, substrate_dimensions, film_material,
                                         external_id, supplier, description, tags))
        if user_id:
            pending = _hand_over(sample, user_id, by_id, by_admin)
        return sample

    sample = new_sample()
    files = chosen_files(files)
    error = await _validate(request, db, sample, files, has_spec=False)
    if not error and sample.sample_type == "collaboration":
        initials = (await db.get(Project, sample.project_id)).code
    elif not error and not initials:
        error = t(request, "That researcher hasn't set their initials yet, so their samples can't get an ID.")
    if error:
        return templates.TemplateResponse(
            "samples/form.html", await _form_context(db, request, current_user, sample, False, error),
            status_code=400)

    # Two people creating samples at once could race for the same number; retry.
    for _ in range(5):
        sample.code = await next_code(db, initials)
        db.add(sample)
        try:
            await db.flush()
            break
        except IntegrityError:
            await db.rollback()
            sample = new_sample()
    for f in files:
        await save_upload(f, "sample", sample.id, db, uploaded_by=username)
    await db.commit()
    if pending:
        request.session["flash"] = t(
            request, "Created for {name}. They'll be asked to confirm it; meanwhile you can edit it.",
            name=owner_name)
        await _ask_to_confirm(request, by_name, owner_name, owner_email, [sample])
    return RedirectResponse(f"/samples/{sample.id}", status_code=303)


@router.post("/{sample_id}/confirm")
async def confirm_sample(
    request: Request,
    sample_id: int,
    accept: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """The owner accepts a sample assigned to them, or declines it, which
    hands it back to whoever assigned it (its ID doesn't change)."""
    sample = await load_sample(db, sample_id, current_user, "summary")
    if sample.owner_id != current_user.id or not sample.requested_by_id:
        raise HTTPException(status_code=403, detail="There's nothing for you to confirm on this sample.")
    if accept:
        request.session["flash"] = t(request, "Sample confirmed: it's now in your samples.")
    else:
        giver = sample.requested_by
        sample.shares = [sh for sh in sample.shares if sh.user_id != giver.id]
        sample.owner_id = giver.id
        request.session["flash"] = t(request, "Declined: {sample} now belongs to {name}.",
                                      sample=sample.title, name=giver.display_name)
    sample.requested_by_id = None
    await db.commit()
    if not accept and settings.SMTP_PASSWORD and giver.email:
        try:
            await send_declined_email(giver.email, current_user.display_name, sample)
        except Exception:
            pass  # they'll still find it in their samples
    return RedirectResponse(f"/samples/{sample_id}" if accept else "/samples/", status_code=303)


@router.get("/{sample_id}", response_class=HTMLResponse)
async def sample_detail(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample_full(db, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    viewable = can_view(current_user, sample)
    fam = await load_family(db, sample)
    items = fam["family"].timeline(sample)

    # Viewing a piece includes its inherited history; inherited entries are
    # also visible to whoever can view the sample they're recorded on.
    def visible(item):
        return (viewable or is_performer(current_user, item.entry)
                or (item.source is not sample and can_view(current_user, item.source)))

    shown = [i for i in items if visible(i)]
    step_attachments = await _attachments_for(db, "step", [i.entry.id for i in shown if i.kind == "process"])
    analysis_attachments = await _attachments_for(db, "analysis", [i.entry.id for i in shown if i.kind == "analysis"])

    runs = await _run_samples(db, [i.entry for i in items if i.entry.run_id], sample.id)

    own_count = sum(1 for i in items if i.source is sample)
    timeline, own_index = [], 0
    for item in items:
        e, inherited = item.entry, item.source is not sample
        path = "steps" if item.kind == "process" else "analyses"
        attachments = step_attachments if item.kind == "process" else analysis_attachments
        timeline.append({
            "kind": item.kind,
            "id": e.id,
            "type_name": item.technique,
            "params": describe(e.parameters, (e.step_type if item.kind == "process" else e.analysis_type).parameter_schema),
            "location": e.location,
            "run": runs.get(e.run_id, []) if e.run_id else [],
            "notes": e.notes,
            "performed_by": e.performer_name,
            "editable": not inherited and can_edit_entry(current_user, sample, e),
            "performed_at": e.performed_at,
            "visible": visible(item),
            "inherited": inherited,
            "source": item.source,
            "first_own": not inherited and own_index == 0,
            "last_own": not inherited and own_index == own_count - 1,
            "pieces": fam["pieces_by_cut"].get(e.id, []) if not inherited else [],
            "photos": [a for a in attachments.get(e.id, []) if _is_image(a)],
            "files": [a for a in attachments.get(e.id, []) if not _is_image(a)],
            "edit_url": f"/samples/{sample_id}/{path}/{e.id}/edit",
            "delete_url": f"/samples/{sample_id}/{path}/{e.id}/delete",
        })
        own_index += not inherited

    owner = is_owner(current_user, sample)
    spec_files = (await _attachments_for(db, "sample", [sample_id]))[sample_id] if viewable else []
    return templates.TemplateResponse("samples/detail.html", {
        "spec_files": spec_files,
        "request": request,
        "sample": sample,
        "timeline": timeline,
        "has_inherited": own_count < len(items),
        "performed_any": any(is_performer(current_user, i.entry) for i in items),
        "parent": fam["parent"],
        "cut": fam["cut"],
        "siblings": fam["siblings"],
        "current_user": current_user,
        "can_view": viewable,
        "can_edit": can_edit(current_user, sample),
        "is_owner": owner,
        "share_candidates": await _share_candidates(db, sample) if owner else [],
        "owner_user": (await db.get(User, sample.owner_id)) if sample.owner_id else None,
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


async def _run_samples(db: AsyncSession, entries, sample_id: int) -> dict[str, list[Sample]]:
    """For entries recorded on several samples at once: run id → the other samples."""
    run_ids = {e.run_id for e in entries}
    runs: dict[str, list[Sample]] = {}
    if run_ids:
        for model in (ProcessStep, Analysis):
            rows = await db.execute(select(model.run_id, Sample).join(Sample, Sample.id == model.sample_id)
                                    .where(model.run_id.in_(run_ids), Sample.id != sample_id).order_by(Sample.code))
            for run_id, s in rows.all():
                runs.setdefault(run_id, []).append(s)
    return runs


async def _share_candidates(db: AsyncSession, sample: Sample) -> list[User]:
    """Users who could be given access: not the owner, not admins, not already shared."""
    taken = {sh.user_id for sh in sample.shares} | {sample.owner_id}
    users = (await db.execute(select(User).where(User.is_admin.is_(False)).order_by(User.username))).scalars()
    return [u for u in users if u.id not in taken]


@router.get("/{sample_id}/edit", response_class=HTMLResponse)
async def edit_sample_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    return templates.TemplateResponse(
        "samples/form.html", await _form_context(db, request, current_user, sample, editing=True))


@router.post("/{sample_id}/edit")
async def update_sample(
    request: Request,
    sample_id: int,
    sample_type: str = Form("thin_film"),
    label: str = Form(""),
    substrate_id: str = Form(""),
    project_id: str = Form(""),
    substrate_dimensions: str = Form(""),
    film_material: str = Form(""),
    external_id: str = Form(""),
    supplier: str = Form(""),
    description: str = Form(""),
    tags: str = Form(""),
    owner_id: str = Form(None),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    was_owner = sample.owner_id == current_user.id
    _apply_form(sample, _form_fields(sample_type, label, substrate_id, project_id, substrate_dimensions, film_material,
                                     external_id, supplier, description, tags))
    has_spec = bool((await _attachments_for(db, "sample", [sample_id]))[sample_id])
    files = chosen_files(files)
    error = await _validate(request, db, sample, files, has_spec)
    if error:
        response = templates.TemplateResponse(  # renders now, before the rollback expires `sample`
            "samples/form.html", await _form_context(db, request, current_user, sample, True, error),
            status_code=400)
        await db.rollback()  # don't keep the invalid changes in this session
        return response
    # Admins reassign ownership directly; owners can give the sample to
    # someone else, who has to confirm. The sample ID keeps the original initials.
    new_owner = None
    if owner_id and owner_id.isdigit() and int(owner_id) != sample.owner_id and (current_user.is_admin or was_owner):
        new_owner = await db.get(User, int(owner_id))
    elif owner_id == "" and current_user.is_admin:
        sample.owner_id = sample.requested_by_id = None
    pending = new_owner is not None and _hand_over(sample, new_owner.id, current_user.id, current_user.is_admin)
    for f in files:
        await save_upload(f, "sample", sample.id, db, uploaded_by=current_user.username)
    await db.commit()
    if pending:
        request.session["flash"] = t(
            request, "Given to {name}. They'll be asked to confirm it; you keep edit access.",
            name=new_owner.display_name)
        await _ask_to_confirm(request, current_user.display_name, new_owner.display_name, new_owner.email, [sample])
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/recode")
async def recode_sample(
    request: Request,
    sample_id: int,
    prefix: str = Form(""),
    code: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Admins: give the sample a new ID, either the next free number under a
    researcher's initials / a project's code, or one typed in. Its pieces and
    uploads folders follow. The old ID becomes free."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only admins can change a sample's ID.")
    sample = await load_sample(db, sample_id, current_user, "owner")
    back = RedirectResponse(f"/samples/{sample_id}/edit", status_code=303)
    old = sample.code
    new_code = code.strip().upper()
    if not new_code:
        kind, _, ident = prefix.partition(":")
        source = (await db.get(User if kind == "user" else Project, int(ident))
                  if ident.isdigit() and kind in ("user", "project") else None)
        initials = (source.initials if kind == "user" else source.code) if source else None
        year = int(old.split("-")[1]) if old and old.count("-") >= 2 and old.split("-")[1].isdigit() else None
        if not initials:
            request.session["flash_error"] = t(request, "Choose whose initials or which project's code to use, or type an ID.")
            return back
        new_code = await next_code(db, initials, year)
    try:
        change = await recode.plan(db, sample, new_code)
        await recode.apply(db, change)
        try:
            await db.commit()
        except Exception:
            recode.undo_move(change.folders)
            raise
    except recode.RecodeError as e:
        await db.rollback()
        request.session["flash_error"] = t(request, str(e))
        return back
    log.info("%s changed sample ID %s to %s (%d samples renamed)", current_user.username, old, new_code, len(change.codes))
    request.session["flash"] = t(request, "ID changed from {old} to {new}.", old=old, new=new_code)
    owner = sample.owner
    if owner and owner.id != current_user.id and settings.SMTP_PASSWORD:
        if not owner.email:
            request.session["flash_error"] = t(request, "{name} has no email address, so tell them about the new ID.",
                                               name=owner.display_name)
        else:
            try:
                await send_recoded_email(owner.email, current_user.display_name, sample, old, change.codes)
            except Exception as exc:
                request.session["flash_error"] = t(request, "Couldn't email {name} ({error}); tell them about the new ID.",
                                                   name=owner.display_name, error=exc)
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/delete")
async def delete_sample(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    pieces = await pieces_of(db, sample_id)
    if pieces:
        request.session["flash_error"] = (
            t(request, "Can't delete: 1 piece was cut from this sample and inherits its history. "
                       "Delete the piece first.") if len(pieces) == 1 else
            t(request, "Can't delete: {n} pieces were cut from this sample and inherit its history. "
                       "Delete the pieces first.", n=len(pieces)))
        return RedirectResponse(f"/samples/{sample_id}", status_code=303)
    await db.delete(sample)
    await db.commit()
    return RedirectResponse("/samples/", status_code=303)


# ── Cutting into pieces ───────────────────────────────────────────────────────


@router.get("/{sample_id}/cut", response_class=HTMLResponse)
async def cut_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    codes, ref_code = await piece_codes(db, sample, 50, reference=True)
    return templates.TemplateResponse("samples/cut.html", {
        "request": request,
        "sample": sample,
        "next_codes": codes,
        "ref_code": ref_code,
        "researchers": await _researchers(db),
        "options": await option_lists(db),
        "location_list": LOCATION_LIST,
        "default_location": DEFAULT_LOCATION,
        "flash_error": request.session.pop("flash_error", None),
        "current_user": current_user,
    })


@router.post("/{sample_id}/cut")
async def cut_sample(
    request: Request,
    sample_id: int,
    piece_labels: list[str] = Form([]),
    piece_dimensions: list[str] = Form([]),
    piece_owners: list[str] = Form([]),
    keep_reference: str = Form(""),
    reference_owner: str = Form(""),
    reference_label: str = Form(""),
    reference_dimensions: str = Form(""),
    method: str = Form(""),
    location: str = Form(""),
    notes: str = Form(""),
    performed_at: str = Form(""),
    cut_by: str = Form(""),
    photos: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Record a Cut step on the sample and create one sample per piece.

    Pieces get the parent's ID plus a suffix and copy its type, substrate,
    materials, tags and shares. Each goes to the researcher chosen for it,
    by default whoever cut the sample ("Cut by", recorded as the Cut step's
    performer). Giving a piece to someone other than the parent's owner goes
    through _hand_over; the parent's owner keeps edit access to it."""
    parent = await load_sample(db, sample_id, current_user, "edit")
    cutter = (await db.get(User, int(cut_by)) if cut_by.isdigit() else None) or current_user
    piece_owners += [""] * (len(piece_labels) - len(piece_owners))
    pieces = [(lbl.strip(), dims.strip(), False, own)
              for lbl, dims, own in zip(piece_labels, piece_dimensions, piece_owners)]
    if keep_reference:
        pieces.append((reference_label.strip(), reference_dimensions.strip(), True, reference_owner))
    if not pieces:
        request.session["flash_error"] = t(request, "Cut into at least one piece.")
        return RedirectResponse(f"/samples/{sample_id}/cut", status_code=303)
    codes, ref_code = await piece_codes(db, parent, sum(not ref for _, _, ref, _ in pieces), bool(keep_reference))
    codes = iter(codes)

    cut_type = (await db.execute(
        select(ProcessStepType).where(ProcessStepType.name == CUT_TYPE_NAME))).scalar_one_or_none()
    if cut_type is None:  # renamed or deleted by an admin: recreate it
        cut_type = ProcessStepType(**next(t for t in PROCESS_STEP_TYPES if t["name"] == CUT_TYPE_NAME))
        db.add(cut_type)
        await db.flush()

    params = {"method": method.strip(), "pieces": len(pieces)} if method.strip() else {"pieces": len(pieces)}
    cut = ProcessStep(
        sample_id=sample_id,
        step_type_id=cut_type.id,
        parameters=params,
        notes=notes or None,
        performer_id=cutter.id,
        performed_at=parse_date(performed_at),
        location=location.strip() or None,
    )
    db.add(cut)
    await db.flush()
    await tl.place_new(db, cut)
    # Photos of the pieces (ideally labelled) go on the Cut step
    for f in chosen_files(photos):
        await save_upload(f, "step", cut.id, db, uploaded_by=current_user.username, photo=True)
    await remember(db, [("cut_method", method.strip()), (LOCATION_LIST, location.strip())], current_user.id)

    owner_id = parent.owner_id or current_user.id
    pieces = [(*rest, o if o.isdigit() else str(cutter.id)) for *rest, o in pieces]
    chosen = {int(o) for *_, o in pieces}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(chosen)))).scalars()} if chosen else {}
    to_confirm: dict[int, list[Sample]] = {}
    for label, dims, is_ref, piece_owner in pieces:
        piece = Sample(
            code=ref_code if is_ref else next(codes),
            label=label or None,
            sample_type=parent.sample_type,
            substrate_id=parent.substrate_id,
            external_id=parent.external_id,
            project_id=parent.project_id,
            supplier=parent.supplier,
            film_material=parent.film_material,
            substrate_dimensions=dims or None,
            tags=list(parent.tags) if parent.tags else None,
            owner_id=owner_id,
            cut_step_id=cut.id,
            is_reference=is_ref,
        )
        piece.shares = [SampleShare(user_id=sh.user_id, can_edit=sh.can_edit) for sh in parent.shares]
        target = users.get(int(piece_owner))
        if target and target.id != owner_id:
            if _hand_over(piece, target.id, current_user.id, current_user.is_admin):
                to_confirm.setdefault(target.id, []).append(piece)
            if parent.owner_id:
                _set_share(piece, parent.owner_id, True)
        elif current_user.id != owner_id and not current_user.is_admin:
            _set_share(piece, current_user.id, True)
        db.add(piece)
    await db.commit()
    msg = (t(request, "Cut into 1 piece.") if len(pieces) == 1 else
           t(request, "Cut into {n} pieces.", n=len(pieces)))
    if to_confirm:
        names = ", ".join(users[uid].display_name for uid in to_confirm)
        msg += " " + (t(request, "{name} will be asked to confirm theirs.", name=names) if len(to_confirm) == 1 else
                      t(request, "{names} will be asked to confirm theirs.", names=names))
    request.session["flash"] = msg
    for uid, given in to_confirm.items():
        await _ask_to_confirm(request, current_user.display_name, users[uid].display_name, users[uid].email, given)
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


# ── Assigning samples to other researchers ───────────────────────────────────

async def _researchers(db: AsyncSession) -> list[User]:
    """Users a sample can belong to (they need initials for sample IDs)."""
    return (await db.execute(select(User).where(User.initials.is_not(None)).order_by(User.username))).scalars().all()


def _hand_over(sample: Sample, owner_id: int, by_id: int, by_admin: bool) -> bool:
    """Make `owner_id` the sample's owner. Giving it to someone else waits for
    their confirmation, unless an admin does it: meanwhile the giver keeps
    edit access, and gets the sample back if they decline. Returns True if
    it's waiting for confirmation."""
    sample.owner_id = owner_id
    sample.shares = [sh for sh in sample.shares if sh.user_id != owner_id]
    if owner_id == by_id or by_admin:
        sample.requested_by_id = None
        return False
    sample.requested_by_id = by_id
    _set_share(sample, by_id, True)
    return True


async def _ask_to_confirm(request: Request, giver: str, owner_name: str, owner_email: str | None,
                          samples: list[Sample]):
    """Email the new owner asking them to confirm. Call after committing."""
    if not settings.SMTP_PASSWORD:
        return
    if not owner_email:
        request.session["flash_error"] = t(
            request, "{name} has no email address, so tell them to confirm it on the site.", name=owner_name)
        return
    try:
        await send_confirm_samples_email(owner_email, giver, samples)
    except Exception as exc:
        request.session["flash_error"] = t(
            request, "Couldn't email {name} ({error}); tell them to confirm it on the site.",
            name=owner_name, error=exc)


# ── Sharing ───────────────────────────────────────────────────────────────────

def _set_share(sample: Sample, user_id: int, can_edit_: bool):
    share = next((sh for sh in sample.shares if sh.user_id == user_id), None)
    if share:
        share.can_edit = can_edit_
    elif user_id != sample.owner_id:
        sample.shares.append(SampleShare(user_id=user_id, can_edit=can_edit_))


@router.post("/{sample_id}/shares")
async def add_share(
    sample_id: int,
    user_id: int = Form(...),
    access: str = Form("view"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    _set_share(sample, user_id, access == "edit")
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#sharing", status_code=303)


@router.post("/{sample_id}/shares/{share_id}/delete")
async def remove_share(
    sample_id: int,
    share_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    share = next((sh for sh in sample.shares if sh.id == share_id), None)
    if share:
        sample.shares.remove(share)
        await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#sharing", status_code=303)


@router.post("/share")
async def share_many(
    request: Request,
    sample_ids: list[int] = Form([]),
    user_id: int = Form(...),
    access: str = Form("view"),
    back: str = Form("/search"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Share several samples at once (from the search page). Samples the
    current user doesn't own are skipped."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    samples = (await db.execute(select(Sample).where(Sample.id.in_(sample_ids)))).scalars().all() if sample_ids else []
    shared = [s for s in samples if is_owner(current_user, s)]
    for s in shared:
        _set_share(s, user_id, access == "edit")
    await db.commit()
    skipped = len(samples) - len(shared)
    if access == "edit":
        msg = (t(request, "Shared 1 sample with {name} (edit).", name=target.display_name) if len(shared) == 1 else
               t(request, "Shared {n} samples with {name} (edit).", n=len(shared), name=target.display_name))
    else:
        msg = (t(request, "Shared 1 sample with {name} (view).", name=target.display_name) if len(shared) == 1 else
               t(request, "Shared {n} samples with {name} (view).", n=len(shared), name=target.display_name))
    if skipped:
        msg += " " + (t(request, "Skipped 1 you don't own.") if skipped == 1 else
                      t(request, "Skipped {n} you don't own.", n=skipped))
    request.session["flash"] = msg
    # Only redirect within the app
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/search", status_code=303)


@router.post("/{sample_id}/timeline/move")
async def move_timeline_entry(
    sample_id: int,
    kind: str = Form(...),
    entry_id: int = Form(...),
    direction: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    model = ProcessStep if kind == "process" else Analysis
    entry = (await db.execute(
        select(model).where(model.id == entry_id, model.sample_id == sample_id)
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await tl.move(db, sample_id, entry, direction)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/timeline/sort-by-date")
async def sort_timeline_by_date(
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    await tl.sort_by_date(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
