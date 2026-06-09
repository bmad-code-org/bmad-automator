Execute the Quick Dev workflow for story {{story_id}}.

{{skill_line}}{{workflow_line}}{{instructions_line}}{{checklist_line}}{{template_line}}Story file: _bmad-output/implementation-artifacts/{{story_prefix}}-*.md
Story ID: {{story_id}}

Quick Dev owns planning, coding, test generation, and review for this story.

Requirements:
- Use the existing BMAD story tracking artifacts: task checkboxes, Dev Agent Record, File List, story Status, and sprint-status.yaml.
- Use subagents for planning, implementation, test generation, and review when they materially improve throughput or quality.
- Keep subagent write scopes disjoint when running them in parallel.
- Run the relevant tests or verification commands.
- Update the story file and sprint-status.yaml through the normal story workflow contract.
- Mark the story done only when no critical issues remain.
- Do not wait for user input.

{{extra_instruction}}
