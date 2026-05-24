---
type: module
status: active
source: mobile/src/stores/gradingStore.ts
storage-key: cardchecker-grading
persisted: partial (history + preferences)
created: 2026-05-21
updated: 2026-05-21
area: [mobile, state]
tags: [zustand, grading]
related: [[_MOC]], [[../screens/grading-flow]]
---

# gradingStore

> **TL;DR**: Grading session (ephemeral) + history (persisted, max 100) + grading service preferences.

## State

### Session (ephemeral)

```typescript
{
  sessionCardId: string | null,
  sessionCardName: string | null,
  sessionRawPrice: number,
  photos: GradePhoto[],
  status: 'idle' | 'capturing' | 'processing' | 'done' | 'error',
  currentResult: GradeResult | null,
  processingPhase: string,         // "Analyzing surface...", etc.
  error: string | null
}
```

### Preferences (persisted)

```typescript
{
  selectedService: 'PSA' | 'CGC' | 'BGS',
  selectedTier: string,             // e.g. "Standard"
  customShippingCost: number
}
```

### History (persisted, max 100)

```typescript
{
  history: GradingHistoryItem[]
}

type GradingHistoryItem = {
  id, cardId, cardName, grade, gradeName,
  confidence, photoCount, timestamp
}
```

## Actions — Session

- `startSession(cardId, cardName, rawPrice)`
- `addPhoto(photo)` — replaces photo of same type
- `removePhoto(type)`
- `setStatus(status)`, `setProcessingPhase(phase)`
- `setResult(result)`, `setError(error)`
- `clearSession()`

## Actions — Preferences

- `setSelectedService('PSA' | 'CGC' | 'BGS')`
- `setSelectedTier(tier)`
- `setCustomShippingCost(amount)`

## Actions — History

- `saveToHistory()` — commits current session to history
- `clearHistory()`

## Computed

- `getPhotoByType(type)` → `GradePhoto | undefined`
- `getRequiredPhotosCount()` → count of front + back
- `canSubmit()` → true if has front + back

## Persistence

- Key: `cardchecker-grading`
- `partialize: (state) => ({ history, selectedService, selectedTier, customShippingCost })`
- Session НЕ persisted

## GradePhoto types

- `front` (required)
- `back` (required)
- `top-closeup`, `bottom-closeup`, `angled-light` (optional)

## Используется в

- `app/grade/capture.tsx` — photo capture flow
- `app/grade/result.tsx` — `saveToHistory()`, ROI display
- `app/grade/history.tsx` — list display

## Daily/Monthly limits

| Tier | Grades |
|------|--------|
| Free | 3/week |
| Plus | 50/month |
| Pro | 300/month |

## Связанные

- All stores: [[_MOC]]
- Grading flow: [[../screens/grading-flow]]
- API: `/gemini/grade` endpoint
- Defect detection roadmap: [[../../02-grading/defect-detection/architecture]]
