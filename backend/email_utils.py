"""Email sending helpers using Gmail SMTP.

Emails are bilingual: Portuguese first, then English, since we don't know
which the reader prefers."""
import aiosmtplib
from email.message import EmailMessage
from backend.config import settings


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on failure."""
    msg = EmailMessage()
    msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.SMTP_USER}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        start_tls=True,
        username=settings.SMTP_USER,
        password=settings.SMTP_PASSWORD,
    )


async def send_admin_message(to: str, subject: str, body: str) -> None:
    """A free-text message written by an admin, sent as-is."""
    await send_email(to, subject, f"{body.rstrip()}\n\n— CTN Logbook\n")


def _bilingual(pt: str, en: str) -> str:
    return f"""\
{pt.rstrip()}

----------------------------------------------------------------
(English below)

{en.rstrip()}

— CTN Logbook
"""


async def send_welcome_email(
    to: str,
    username: str,
    temp_password: str,
    magic_link: str | None = None,
) -> None:
    """Sent when an admin creates a new account."""
    if magic_link:
        link_pt = f"""\
Clique na ligação abaixo para entrar e escolher a sua palavra-passe (válida durante 72 horas):

  {magic_link}

Ou entre com as credenciais temporárias:"""
        link_en = f"""\
Click the link below to log in and set your own password (valid for 72 hours):

  {magic_link}

Or log in manually with your temporary credentials:"""
    else:
        link_pt = "Entre com as credenciais temporárias em:"
        link_en = "Log in with your temporary credentials at:"

    pt = f"""\
Olá,

Foi criada uma conta para si no CTN Thin Film Logbook.

  Utilizador:                 {username}
  Palavra-passe temporária:   {temp_password}

{link_pt}
  {settings.BASE_URL}/login

No primeiro acesso ser-lhe-á pedido que escolha uma nova palavra-passe.
A ligação acima só pode ser usada uma vez; depois disso, use o seu nome de
utilizador e a palavra-passe que escolheu.

Se não estava à espera deste email, pode ignorá-lo.
"""
    en = f"""\
Hello,

An account has been created for you on the CTN Thin Film Logbook.

  Username:           {username}
  Temporary password: {temp_password}

{link_en}
  {settings.BASE_URL}/login

You will be asked to choose a new password on your first login.
The magic link above can only be used once — after that, use your username
and the password you set.

If you didn't expect this email, you can ignore it.
"""
    await send_email(to, "CTN Logbook — a sua nova conta / your new account", _bilingual(pt, en))


async def send_password_reset_email(
    to: str,
    username: str,
    magic_link: str,
) -> None:
    """Sent when a user requests a password reset."""
    pt = f"""\
Olá,

Foi pedida a reposição da palavra-passe da conta do CTN Thin Film Logbook
associada a este endereço de email.

  Utilizador: {username}

Clique na ligação abaixo para escolher uma nova palavra-passe (válida durante 72 horas):

  {magic_link}

A ligação só pode ser usada uma vez. Se não fez este pedido, pode ignorar
este email: a sua palavra-passe não foi alterada.
"""
    en = f"""\
Hello,

A password reset was requested for the CTN Thin Film Logbook account
associated with this email address.

  Username: {username}

Click the link below to set a new password (valid for 72 hours):

  {magic_link}

This link can only be used once. If you didn't request a reset, you can
safely ignore this email — your password has not been changed.
"""
    await send_email(to, "CTN Logbook — reposição da palavra-passe / password reset", _bilingual(pt, en))


def _sample_lines(samples) -> str:
    return "\n".join(
        f"  {s.title}{f' ({s.label})' if s.label else ''}: {settings.BASE_URL}/samples/{s.id}" for s in samples)


async def send_confirm_samples_email(to: str, giver: str, samples) -> None:
    """Sent when someone creates or hands over samples on the recipient's behalf."""
    many = len(samples) != 1
    lines = _sample_lines(samples)
    if many:
        pt = f"""\
Olá,

{giver} atribuiu-lhe estas amostras no CTN Thin Film Logbook:

{lines}

Abra cada uma e clique em Aceitar se forem suas, ou em Recusar para as
devolver a {giver}. Até lá, {giver} pode continuar a editá-las. Também as
encontra no topo da sua página de Amostras:

  {settings.BASE_URL}/samples/
"""
        en = f"""\
Hello,

{giver} assigned these samples to you on the CTN Thin Film Logbook:

{lines}

Please open each one and click Accept if they are yours, or Decline to
hand them back to {giver}. Until then {giver} can still edit them. You can
also find them at the top of your Samples page:

  {settings.BASE_URL}/samples/
"""
        subject = f"CTN Logbook — confirme as amostras de {giver} / please confirm samples from {giver}"
    else:
        pt = f"""\
Olá,

{giver} atribuiu-lhe esta amostra no CTN Thin Film Logbook:

{lines}

Abra-a e clique em Aceitar se for sua, ou em Recusar para a devolver a
{giver}. Até lá, {giver} pode continuar a editá-la. Também a encontra no
topo da sua página de Amostras:

  {settings.BASE_URL}/samples/
"""
        en = f"""\
Hello,

{giver} assigned this sample to you on the CTN Thin Film Logbook:

{lines}

Please open it and click Accept if it is yours, or Decline to hand it
back to {giver}. Until then {giver} can still edit it. You can also find it
at the top of your Samples page:

  {settings.BASE_URL}/samples/
"""
        subject = f"CTN Logbook — confirme uma amostra de {giver} / please confirm a sample from {giver}"
    await send_email(to, subject, _bilingual(pt, en))


async def send_declined_email(to: str, decliner: str, sample) -> None:
    """Sent to the person who assigned a sample when the recipient declines it."""
    lines = _sample_lines([sample])
    pt = f"""\
Olá,

{decliner} recusou uma amostra que lhe atribuiu, por isso a amostra voltou a ser sua:

{lines}
"""
    en = f"""\
Hello,

{decliner} declined a sample you assigned to them, so it now belongs to you:

{lines}
"""
    await send_email(to, f"CTN Logbook — {sample.title} recusada por / declined by {decliner}", _bilingual(pt, en))


async def send_recoded_email(to: str, admin: str, sample, old_code: str, renamed: dict[str, str]) -> None:
    """Sent to a sample's owner when an admin changes its ID (and its pieces', if any)."""
    others = "\n".join(f"  {o} → {n}" for o, n in renamed.items() if o != old_code)
    extra_pt = f"\nAs peças cortadas desta amostra também foram renomeadas:\n{others}\n" if others else ""
    extra_en = f"\nThe pieces cut from this sample were renamed too:\n{others}\n" if others else ""
    pt = f"""\
Olá,

{admin} alterou o ID de uma das suas amostras no CTN Thin Film Logbook:

  {old_code} → {sample.title}
{extra_pt}
Os dados e ficheiros mantêm-se; só o ID mudou. Se tinha o ID antigo apontado noutro lado, atualize-o:

{_sample_lines([sample])}
"""
    en = f"""\
Hello,

{admin} changed the ID of one of your samples in the CTN Thin Film Logbook:

  {old_code} → {sample.title}
{extra_en}
The data and files are unchanged; only the ID is different. If you noted the old ID anywhere else, please update it:

{_sample_lines([sample])}
"""
    await send_email(to, f"CTN Logbook — ID alterado / ID changed: {old_code} → {sample.title}", _bilingual(pt, en))


async def send_performer_email(to: str, giver: str, samples: list, entry_name: str) -> None:
    """Sent when someone records the recipient as having performed a step or
    analysis, on one sample or (a run) several."""
    lines, many = _sample_lines(samples), len(samples) != 1
    pt = f"""\
Olá,

{giver} registou que realizou "{entry_name}" {'nestas amostras' if many else 'nesta amostra'} do CTN Thin Film Logbook:

{lines}

Pode ver e editar {'esses registos' if many else 'esse registo'} (parâmetros, notas, fotografias e ficheiros),
mesmo sem acesso ao resto {'das amostras' if many else 'da amostra'}.
"""
    en = f"""\
Hello,

{giver} recorded you as having performed "{entry_name}" on {'these samples' if many else 'this sample'} in the CTN Thin Film Logbook:

{lines}

You can see and edit {'those entries' if many else 'that entry'} (parameters, notes, photos and files), even
without access to the rest of the {'samples' if many else 'sample'}.
"""
    titles = ", ".join(s.title for s in samples)
    await send_email(to, f"CTN Logbook — {entry_name}: {titles}", _bilingual(pt, en))
