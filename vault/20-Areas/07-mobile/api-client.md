---
type: module
status: active
source: mobile/src/api/
created: 2026-05-21
updated: 2026-05-21
area: [mobile, backend, api]
tags: [api-client, http]
related: [[architecture]], [[../06-api/_MOC]]
---

# Mobile API Client

> **TL;DR**: Typed HTTP client с auto Base URL detection, mock mode toggle, AbortController timeouts.

## Folder

`mobile/src/api/`

- `client.ts` — typed fetch wrappers
- `cardApi.ts` — card identification endpoints
- `gradingApi.ts` — grading endpoints
- `types.ts` — type definitions
- `mockData.ts` — mock responses для dev
- `index.ts` — barrel export

## Base URL detection

```typescript
const __DEV__ = ...; // Expo flag
const isAndroid = Platform.OS === 'android';

BASE_URL =
  __DEV__
    ? (isAndroid ? 'http://10.0.2.2:8000' : 'http://localhost:8000')
    : 'https://api.cardchecker.app';
```

- **Production**: `https://api.cardchecker.app` (фактически alias на `bees.cardchecker.app`)
- **Dev iOS / Web**: `http://localhost:8000`
- **Dev Android Emulator**: `http://10.0.2.2:8000` (special hostname для host machine)

## Mock mode

Toggle:
- `EXPO_PUBLIC_USE_MOCK` env var
- Или `app.json` `extra.useMock`
- Default: `true` in dev, `false` in prod

Mock возвращает realistic data с timed delays (имитация network).

## `client.ts` exports

```typescript
apiClient.get<T>(path, options) → Promise<T>           // default timeout 10s
apiClient.post<T>(path, body, options) → Promise<T>    // default timeout 15s
apiClient.uploadImage<T>(path, imageUri, params, options) → Promise<T>  // 30s timeout

apiClient.BASE_URL      // current
apiClient.USE_MOCK      // boolean

class ApiError {        // custom error
  status: number,
  data: any
}
```

Timeout handling: `AbortController` + `setTimeout`.

## `cardApi.ts` — card endpoints

### `identifyCardV2(imageUri, locale?)`

- POST `/identify-v2` (multipart)
- Query: `?locale=en`
- Response: `IdentifyV2Response` (top_match, alternatives, OCR data)
- Mock: 90% success rate, 1.2-2s delay

### `getCardDetail(idProduct)`

- GET `/card/{id}`
- Response: `CardDetailResponse`
- Mock: 500ms delay

### `getHealth()`

- GET `/health`
- Response: server stats
- Mock: returns 42k indexed cards, 3 languages

## `gradingApi.ts` — grading

### `gradeCard(cardId, photos[])`

- POST `/grade` (multipart FormData)
- Body: `card_id`, `photos[]`, `photo_types[]`
- Response: `GradeResponse` (grade, distribution, subgrades, defects, roi)
- Mock: 3-5s delay

## Type definitions (`types.ts`)

Ключевые:
- `SQLCardMatch` — result из identify-v2
- `IdentifyV2Response` — full scan result
- `CardDetailResponse`
- `GradePhoto = { uri: string, type: PhotoSlotType }`
- `GradeResult` — grading output
- `Defect` — `{ id, type, severity, location, description, bbox }`
- `CollectionCard` — extends SQLCardMatch с quantity/condition/notes
- `SubscriptionTier = 'free' | 'standard' | 'premium'`
- `TIER_LIMITS` — feature limits per tier (scans/day, collection size, alerts, export)

## Auth

⚠️ Сейчас нет реальной auth. Headers не добавляются. Когда реализуем — будет `Authorization: Bearer ${token}` через interceptor.

## Связанные

- Backend API MOC: [[../06-api/_MOC]]
- Architecture: [[architecture]]
- Cloud sync project: [[../../10-Projects/2026-Q2-mobile-auth-and-cloud]]
