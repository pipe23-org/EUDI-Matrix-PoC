# element-web-patched

Patched build of [Element Web](https://github.com/element-hq/element-web) v1.12.10 that adds phone number discovery to the invite dialog.

## What's patched

One file: `src/components/views/dialogs/InviteDialog.tsx`. The patch adds:

1. **E.164 phone number detection** — a `looksLikePhoneNumber()` function that recognizes international phone numbers (`+` followed by 7-15 digits, tolerating spaces and dashes).
2. **Identity Service v2 `msisdn` lookup** — when the typed text matches E.164 format and an Identity Server is configured, performs a `lookupThreePid("msisdn", ...)` against it. If a Matrix user is found, displays them as an invitable result.
3. **Help text hint** — appends a "[Patched Element]" note to the invite dialog telling users they can enter a phone number.

The lookup uses Element's existing `IdentityAuthClient` and `MatrixClientPeg` — no new dependencies. Stale results are discarded if the filter text changes between async calls.

## What's NOT patched

- **Authentication/login** — works via standard OIDC delegation (MSC3861) to the provisioning agent. No changes needed.
- **Everything else** — no contact list upload, no phone number hashing beyond what IS v2 requires, no modifications outside `InviteDialog.tsx`.

## Why this patch exists

Element X (next-gen client) has zero Identity Service support — no code, no planned work. Element Web has IS support but its invite dialog only detects email addresses and Matrix IDs, not phone numbers. This minimal patch closes that gap for the PoC: type a phone number, the phonebook returns the user's MXID, start chatting.

## Build

The Dockerfile clones upstream Element Web at a pinned tag, applies the patch, and builds. No fork to maintain — just a patch file and a multi-stage Docker build.

```
docker build -t element-web-patched .
```
