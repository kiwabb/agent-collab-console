# Command Proposal Contract

Use the exact JSON Schema returned by `tools/list`. The envelope has this shape:

```json
{
  "protocolVersion": 1,
  "draftId": "draft-id-from-active-context",
  "expectedHeadSequenceNo": 42,
  "expectedDocumentHash": "sha256:64-lowercase-hex-characters",
  "batch": {
    "commandContractVersion": 1,
    "summary": "Describe one cohesive design change",
    "commands": [
      {
        "kind": "a-kind-advertised-by-active-context"
      }
    ]
  }
}
```

The example shows the envelope only. Never submit the illustrative command kind. Copy a supported command kind and its required fields from the active context's command catalog.

For submission, add:

```json
{
  "clientRequestId": "canonical-lowercase-uuid",
  "message": "Why this change satisfies the user's request",
  "affectedEntityIds": ["exact-id-returned-by-validation"]
}
```

## Invariants

- Keep `draftId`, sequence number, document hash, and command contract version from one active-context read.
- Keep command order deterministic because later commands may depend on entities created earlier in the batch.
- Use stable entity IDs. Do not substitute labels, visible text, DOM selectors, or array positions for IDs.
- Declare every affected entity exactly once.
- Do not include raw HTML, full-document JSON, shell commands, SQL, credentials, or unbounded binary data.
- Treat successful validation as evidence for one exact batch and base only.
- Treat a successful submission receipt as a proposal identity, not proof of Apply or Publish.
