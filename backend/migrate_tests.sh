#!/bin/bash
FILES=$@
for FILE in $FILES; do
  echo "Migrating $FILE..."
  
  # 1. Ensure pytest import
  if ! grep -q "import pytest" "$FILE"; then
    sed -i '' '1i\
import pytest
' "$FILE"
  fi

  # 2. Change test signatures to async
  perl -i -pe 's/\bdef test_/async def test_/g' "$FILE"
  perl -i -pe 's/async async def/async def/g' "$FILE"
  
  # 3. Use async_client
  perl -i -pe 's/\bclient\b/async_client/g' "$FILE"
  perl -i -pe 's/async_client_client/async_client/g' "$FILE"

  # 4. Add mark
  perl -i -0777 -pe 's/\@pytest\.mark\.asyncio\s*\n\s*(async def test_|class Test)/$1/g' "$FILE"
  perl -i -pe 's/^(async def test_)/\@pytest.mark.asyncio\n$1/g' "$FILE"
  perl -i -pe 's/^(class Test)/\@pytest.mark.asyncio\n$1/g' "$FILE"
  
  # 5. Await async_client calls
  perl -i -pe 's/await async_client/async_client/g' "$FILE"
  perl -i -pe 's/async_client\.([a-z]+)\((.*)\)\.json\(\)/(await async_client.$1($2)).json()/g' "$FILE"
  perl -i -pe 's/async_client\.([a-z]+)\((.*)\)\.status_code/(await async_client.$1($2)).status_code/g' "$FILE"
  perl -i -pe 's/(?<!await )async_client\.([a-z]+)\(/await async_client.$1(/g' "$FILE"
  perl -i -pe 's/await \(await async_client/(await async_client/g' "$FILE"

  # 6. Await store/service/manager/api calls
  CORE_METHODS="load_codex_task|save_codex_task|list_codex_tasks|load_codex_workspace|save_codex_workspace|list_codex_workspaces|load_codex_issue|save_codex_issue|list_codex_issues|load_codex_task_messages|save_codex_task_message|load_log_events|append_log_event|reset|load_codex_session|save_codex_session|list_codex_sessions|load_session|save_session|list_sessions|load_help_request|save_help_request|list_help_requests|update_execution_process_status|persist_result|build_prompt|create_session|update_session|plan_task|run_task|retry_task|request_submission|approve|reject|write_input|write_input_async|terminate|terminate_all|start_task_run"
  API_METHODS="send_codex_task_message|create_task|get_task|update_task|delete_task|list_tasks|get_session|create_session|update_session|delete_session|list_sessions|approve_approval|reject_approval|get_approval|list_approvals|request_help_from_runtime"
  
  ALL_METHODS="$CORE_METHODS|$API_METHODS"
  
  # Use safer lookahead to avoid double awaits and word-breaking
  perl -i -pe "s/(?<!await )(?<!await\s)\b([\w.]*)\b($ALL_METHODS)\(/await \$1\$2\(/g" "$FILE"

  # 7. Final Cleanup
  perl -i -pe 's/await await /await /g' "$FILE"
  perl -i -pe 's/await \(await /(await /g' "$FILE"
  perl -i -0777 -pe 's/\@pytest\.mark\.asyncio\s*\n\s*\@pytest\.mark\.asyncio/\@pytest\.mark\.asyncio/g' "$FILE"
  # Fix the "bawait" and "cawait" bugs if they happen
  perl -i -pe 's/await [a-z]await /await /g' "$FILE"
  perl -i -pe 's/await bstrap_module/await bootstrap_module/g' "$FILE"
  perl -i -pe 's/await otstrap_module/await bootstrap_module/g' "$FILE"
  perl -i -pe 's/await odex_store/await codex_store/g' "$FILE"
done
