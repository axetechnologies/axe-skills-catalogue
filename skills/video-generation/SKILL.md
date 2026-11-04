---
name: video-generation
description: Foundational skill for generating new videos from text/image prompts or editing previously generated videos. Handles camera motion, subject descriptions, gender/plurality preservation, and video continuity.
---

# Video Generation Skill

Generate and edit videos using image-to-video, text-to-video, and video-to-video editing instructions.

## Core Rules & Principles

1. **Prompt Formatting:**
   - **New Generation / Text-to-Video / Image-to-Video:** Write a comprehensive generation prompt describing the full scene (subject, background, camera movement, style, lighting, and action).
   - **Video Editing (Modifying Existing Video):** Write an **edit prompt** describing ONLY what needs to change relative to the previous video. Do not restate unchanged original details.
   - **Subject Naming:** Describe the subject rather than naming specific individuals unless explicitly requested by the user. Do not include phrases like "video of" or "a clip showing" — keep prompts centered around noun phrases.
   - **Language:** Prompts provided to the underlying generator must be translated into English while preserving the user's intended target video audio/text language.

2. **Preserving Identity & Attributes:**
   - **Gender & Plurality:** Maintain explicit gender markers (e.g., "female architect", "two male dancers") and singular/plural counts from user queries.
   - **@Handles:** Treat `@handle` tags as direct visual and voice references for specific individuals or characters. Mention them directly in the prompt (e.g., `@John surfing on a wave`).

3. **Reference Mapping:**
   - Attach uploaded image files (e.g., `image.png`), generated image URLs, or audio clips whenever referenced by the user.
   - Reference previous video iterations as `last_generated_video` or `earlier_generated_video` when performing edits or sequential modifications.

---

## Standard Prompt Template

```text
[SUBJECT & ACTION] in a [SETTING / ENVIRONMENT], [LIGHTING & ATMOSPHERE], [CAMERA MOVEMENT / ANGLE], [STYLE & COLOR PALETTE].
```
