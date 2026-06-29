# T93 - Virtual Transcript Annotation Painting

## Goal
Paint evidence block annotations on the virtual transcript surface.

## Background
The annotation model is a core product requirement. It must be visually clear and tied to the transcript text.

**Spec reference:** `08_virtual_transcript_widget_spec.md` section `Annotation Rendering`

## Depends On
- T92

## Scope
- Add virtual annotation rendering for active evidence block
- Paint context range shading for visible context messages
- Paint stronger relevant range shading for visible relevant messages
- Paint hit message marker/shading
- Paint highlighted message marker/shading
- Paint four labeled boundary handles when visible:
  - context start
  - relevant start
  - relevant end
  - context end
- Ensure annotation positions are derived from visible ordinals and virtual layout offsets
- Ensure annotations scroll naturally with text

## Guardrails
- Do not use floating bars detached from text geometry
- Do not draw unlabeled mystery controls
- Do not persist pixel positions
- Do not draw annotations for offscreen messages except optional above/below indicators

## Non-Goals
- Dragging/persistence
- Hit/highlight editing

## Acceptance Criteria
- Active evidence block visibly shades context and relevant ranges
- Hit message is unmistakable
- Highlighted messages are visible
- Four boundary handles are labeled and align with message boundaries
- Handles and shading scroll with the transcript

## Tests
- Add tests for visible annotation geometry calculations
- Add UI smoke tests or render-state tests for context/relevant/hit/highlight visibility
- Add a scroll test proving boundary y positions change with scroll

