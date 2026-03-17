"""Mock EUDI wallet — FastAPI app with terminal TUI for credential selection.

Runs on the host (not Docker) at localhost:8095. The browser is redirected here
by the provisioning agent during login. The terminal shows a rich Panel prompting
the operator to select which wallet identity to present.
"""

import asyncio
import hashlib
import logging

# Suppress uvicorn/fastapi access logs — we have our own TUI
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import httpx  # noqa: E402
from fastapi import FastAPI, Query  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402

from carrier import issue_credential, load_holder_key, load_carrier_key, load_keys_dir  # noqa: E402
from credential import build_vp_token  # noqa: E402

app = FastAPI(title="Mock EUDI Wallet")
console = Console()

# --- Module-level state (set during startup) ---

carrier_key = None
holder_key_a = None
holder_key_b = None
phone_a = "+358401234567"
phone_b = "+358501234567"


def derive_pseudonym(holder_key, client_id):
    """Derive a per-RP pseudonym from the holder's private key and the RP's client_id.

    Uses the full client_id verbatim (including mock: prefix) as domain separator.
    """
    key_bytes = holder_key.export_to_pem(private_key=True, password=None)
    secret = hashlib.sha256(key_bytes).digest()
    return hashlib.sha256(secret + client_id.encode()).hexdigest()


@app.on_event("startup")
async def startup():
    global carrier_key, holder_key_a, holder_key_b

    keys_dir = load_keys_dir()
    console.print("\n[bold]Mock EUDI Wallet[/bold]")
    console.print(f"  Keys directory: {keys_dir.resolve()}")

    # Load keys
    carrier_key = load_carrier_key(keys_dir)
    console.print(f"  Carrier key:    kid={carrier_key['kid']}")

    holder_key_a = load_holder_key(keys_dir, "a")
    holder_key_b = load_holder_key(keys_dir, "b")

    console.print("  Wallet A:")
    console.print(f"    Holder key:   kid={holder_key_a['kid']}")
    console.print(f"    Phone:        {phone_a}")
    console.print("    Pseudonym:    (derived at presentation time)")
    console.print("  Wallet B:")
    console.print(f"    Holder key:   kid={holder_key_b['kid']}")
    console.print(f"    Phone:        {phone_b}")
    console.print("    Pseudonym:    (derived at presentation time)")

    console.print("\n  Listening on http://localhost:8095")
    console.print("  Waiting for authorization requests...\n")


@app.get("/authorize")
async def authorize(
    request_uri: str = Query(...),
    state: str = Query(...),
):
    """Handle browser redirect from provisioning agent.

    Fetches the authorization request, prompts operator for wallet selection
    in the terminal, builds VP token, and redirects browser to Element callback.
    """

    # 1. Fetch authorization request from the provisioning agent
    try:
        async with httpx.AsyncClient(verify=False) as client:  # mkcert self-signed TLS
            resp = await client.get(request_uri)
            resp.raise_for_status()
            auth_request = resp.json()
    except Exception as e:
        console.print(f"[red]Failed to fetch authorization request:[/red] {e}")
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to fetch authorization request: {e}"},
        )

    nonce = auth_request["nonce"]
    response_uri = auth_request["response_uri"]
    client_id = auth_request["client_id"]
    presentation_def = auth_request.get("presentation_definition", {})

    # Extract verifier display name from client_id (handles mock: prefix)
    verifier_display = client_id
    if ":" in client_id:
        verifier_display = client_id.split(":", 1)[1]

    # Build "Requested:" from input_descriptors — each is a separate trust domain
    descriptors = presentation_def.get("input_descriptors", [])
    if descriptors:
        requested_lines = "\n".join(
            f"    {d.get('name', d['id'])}: {d.get('purpose', '')}"
            for d in descriptors
        )
    else:
        requested_lines = "    (no descriptors)"

    # 2. TUI prompt — show panel and wait for operator selection
    panel_text = (
        f"Verifier: [bold]{verifier_display}[/bold]\n"
        f"Requested:\n{requested_lines}\n"
        f"\n"
        f"  [bold][A][/bold] Wallet A  {phone_a}\n"
        f"  [bold][B][/bold] Wallet B  {phone_b}\n"
    )

    console.print()
    console.print(Panel(panel_text, title="Credential Request", border_style="cyan"))

    while True:
        choice = await asyncio.to_thread(input, "  Select [A/B]: ")
        choice = choice.strip().upper()
        if choice == "":
            choice = "A"
        if choice in ("A", "B"):
            break
        console.print("  [yellow]Invalid selection. Enter A or B.[/yellow]")

    # Select key and phone, issue credential on the fly with per-RP pseudonym
    if choice == "A":
        selected_key = holder_key_a
        selected_phone = phone_a
    else:
        selected_key = holder_key_b
        selected_phone = phone_b

    pseudonym = derive_pseudonym(selected_key, client_id)
    console.print(f"  Pseudonym: [dim]{pseudonym[:16]}…[/dim]  (derived from holder key + {verifier_display})")
    selected_credential = issue_credential(carrier_key, selected_key, selected_phone, pseudonym)

    console.print(
        f"  Presenting Wallet {choice} credential to [bold]{verifier_display}[/bold]..."
    )

    # 3. Build VP token
    vp_token = build_vp_token(
        sd_jwt_vc=selected_credential,
        holder_key=selected_key,
        nonce=nonce,
        aud=client_id,
    )

    # 4. POST VP token to the provisioning agent's response endpoint
    try:
        async with httpx.AsyncClient(verify=False) as client:  # mkcert self-signed TLS
            resp = await client.post(
                response_uri,
                json={"vp_token": vp_token, "state": state},
            )
            resp.raise_for_status()
            result = resp.json()
    except Exception as e:
        console.print(f"  [red]Failed to submit VP token:[/red] {e}")
        return JSONResponse(
            status_code=502,
            content={"error": f"Failed to submit VP token: {e}"},
        )

    redirect_url = result["redirect_uri"]
    console.print("  [green]Success[/green] — redirecting browser\n")

    # 5. Redirect browser to Element callback
    return RedirectResponse(url=redirect_url)
