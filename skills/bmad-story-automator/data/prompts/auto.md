Execute the BMAD {{label}} workflow for story {{story_id}}.

{{skill_line}}{{workflow_line}}{{instructions_line}}{{checklist_line}}Story file (use THIS exact file only): `{{implementation_artifacts}}/{{story_key}}.md`
Operate ONLY on that story file. Other epics may have a story with the same bare number (e.g. epic-a-1-2 vs epic-b-1-2) — do NOT match by number or touch any other epic's story; if the exact file above is missing, fall back to `{{implementation_artifacts}}/{{story_prefix}}-*.md` but still restrict to this epic.
Auto-apply all discovered gaps in tests.
