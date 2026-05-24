---
type: module
status: active
source: mobile/src/stores/scanStore.ts
storage-key: cardchecker-scan
persisted: partial (history only)
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [zustand, scan]
related: [[_MOC]], [[../screens/scan-flow]]
---

# scanStore

> **TL;DR**: Current scan session (ephemeral) + scan history (persisted, max 50 items).

## State

### Session (ephemeral, не persisted)

```typescript
{
  imageUri: string | null,
  isScanning: boolean,
  result: IdentifyV2Response | null,
  error: string | null
}
```

### History (persisted, max 50)

```typescript
{
  history: ScanHistoryItem[]  // newest first
}

type ScanHistoryItem = {
  id, imageUri, cardName, setAbbreviation,
  priceTrend, confidence, method,
  timestamp
}
```

## Actions

- `setImage(uri)` — clears error
- `setScanning(bool)`
- `setResult(result)` — sets result, clears scanning/error
- `setError(error)` — sets error, stops scanning
- `clearScan()` — resets session to idle
- `addToHistory(result, imageUri)` — appends if success, caps at 50
- `clearHistory()`

## Persistence

- Key: `cardchecker-scan`
- `partialize: (state) => ({ history: state.history })`
- Session state НЕ восстанавливается — каждое открытие приложения = fresh session

## Используется в

- `app/(tabs)/scan.tsx` — clears at entry
- `app/scan/result.tsx` — entire flow (setScanning → API call → setResult → addToHistory)
- `app/(tabs)/profile.tsx` — `history.length` для stats display

## Daily limit (per tier)

| Tier | Scans/week |
|------|-----------|
| Free | 30 |
| Plus | Unlimited |
| Pro | Unlimited |

⚠️ Enforcement через [[settings-store]] (daily counter), но not actively gated yet.

## Связанные

- All stores: [[_MOC]]
- Scan flow: [[../screens/scan-flow]]
- API: [[../api-client]]
