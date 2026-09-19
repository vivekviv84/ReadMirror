# Audio Speech Recognition Route

## `POST /api/asr/transcribe`

Transcribes an uploaded English recording with the local NVIDIA NeMo `nvidia/parakeet-tdt-0.6b-v2` model. The model loads lazily on the first request.

**Headers:** `Authorization: Bearer <access_token>`

**Multipart fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `audio` | File | Yes | Audio such as WebM, WAV, or OGG |
| `language` | string | No | Only `en` is accepted; defaults to `en` |

```json
{
  "transcript": "hello world"
}
```

Arabic speech recognition and its model/worker queue have been removed.
