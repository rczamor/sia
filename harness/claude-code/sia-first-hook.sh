#!/usr/bin/env sh
# Sia-first UserPromptSubmit hook for Claude Code.
#
# Wire it up in .claude/settings.json (see settings.json in this folder). On every
# user prompt, Claude Code runs this hook and adds its stdout to the model's
# context — a reliable, stateless nudge to treat Sia as the default first stop and
# to record a bypass when it genuinely has to look elsewhere.
#
# This is a soft enforcement: it re-injects the directive every turn rather than
# hard-blocking other tools (which would require fragile cross-invocation state).
# It reads the hook payload on stdin but does not need it; it always emits the
# directive.

cat <<'EOF'
[Sia context policy] Before reasoning about, retrieving for, or answering anything
that touches the operator's own knowledge, projects, decisions, notes, or prior
work — and before reaching for other connectors, local files, or web search — call
sia_build_context(goal) first. Consult other sources only if Sia reports
insufficient coverage. When you do rely on a source outside Sia, call
sia_record_bypass(goal, source, reason) so the gap can be closed. Feed durable new
knowledge back with sia_add_thought / sia_add_source.
EOF
exit 0
