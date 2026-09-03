import unittest
import time
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Load environment before any other module imports to satisfy rulemaking in AGENTS.md
import src.aion_env  # noqa: F401

from src.observability import metrics
from src.observability.hooks_emitter import (
    register_observability_hooks,
    _tool_start_times,
)
from src.runtime.hooks import HookContext, hook_registry


class TestObservabilityMetrics(unittest.TestCase):
    def setUp(self):
        # Clear handlers to avoid duplicate registration between tests
        hook_registry._handlers.clear()
        # Clear metrics dictionary for test isolation
        metrics.aion_turn_duration_seconds.prom_metric._metrics.clear()
        metrics.aion_last_turn_duration_seconds.prom_metric._metrics.clear()
        metrics.aion_messages_total.prom_metric._metrics.clear()
        metrics.aion_tool_calls_total.prom_metric._metrics.clear()
        metrics.aion_llm_tokens_total.prom_metric._metrics.clear()
        # Register hooks
        register_observability_hooks()

    def test_metrics_defined(self):
        """Verify that all our new and existing metrics are correctly defined in metrics.py."""
        self.assertIsNotNone(metrics.aion_messages_total)
        self.assertIsNotNone(metrics.aion_tool_calls_total)
        self.assertIsNotNone(metrics.aion_turn_duration_seconds)
        self.assertIsNotNone(metrics.aion_last_turn_duration_seconds)
        self.assertIsNotNone(metrics.aion_llm_tokens_total)
        self.assertIsNotNone(metrics.aion_llm_turn_tokens)
        self.assertIsNotNone(metrics.aion_llm_turn_calls)
        self.assertIsNotNone(metrics.aion_agent_failures_total)
        self.assertIsNotNone(metrics.aion_mcp_server_healthy)

    def test_on_user_message_hook(self):
        """Verify that the user message hook increments the message counter."""
        ctx = HookContext(
            event="on_user_message",
            tenant_id="test_tenant",
            conversation_id="test_session",
            user_id="test_user",
            profile="test_profile",
            payload={"message": "hello", "attachments": []},
        )

        # Get count before
        try:
            val_before = metrics.aion_messages_total.labels(
                tenant_id="test_tenant",
                profile="test_profile",
                role="user",
                finish_reason="none",
            )._value.get()
        except Exception:
            val_before = 0

        asyncio.run(hook_registry.dispatch("on_user_message", ctx))

        val_after = metrics.aion_messages_total.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            role="user",
            finish_reason="none",
        )._value.get()

        self.assertEqual(val_after, val_before + 1)

    def test_tool_use_hooks_latency(self):
        """Verify that pre_tool_use and post_tool_use hooks measure latency correctly."""
        pre_ctx = HookContext(
            event="pre_tool_use",
            tenant_id="test_tenant",
            conversation_id="test_session",
            user_id="test_user",
            profile="test_profile",
            payload={"tool_name": "test_tool", "server_name": "native", "input": {}},
        )

        post_ctx = HookContext(
            event="post_tool_use",
            tenant_id="test_tenant",
            conversation_id="test_session",
            user_id="test_user",
            profile="test_profile",
            payload={
                "tool_name": "test_tool",
                "server_name": "native",
                "input": {},
                "status": "ok",
            },
        )

        # Dispatch pre_tool_use
        asyncio.run(hook_registry.dispatch("pre_tool_use", pre_ctx))
        self.assertIn(("test_session", "test_tool"), _tool_start_times)

        # Get count before
        try:
            count_before = metrics.aion_tool_calls_total.labels(
                tenant_id="test_tenant",
                profile="test_profile",
                tool_name="test_tool",
                mcp_server="native",
                status="ok",
            )._value.get()
        except Exception:
            count_before = 0

        # Dispatch post_tool_use
        asyncio.run(hook_registry.dispatch("post_tool_use", post_ctx))

        count_after = metrics.aion_tool_calls_total.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            tool_name="test_tool",
            mcp_server="native",
            status="ok",
        )._value.get()

        self.assertEqual(count_after, count_before + 1)
        self.assertNotIn(("test_session", "test_tool"), _tool_start_times)

    def test_post_turn_hook_tokens_and_failures(self):
        """Verify that post_turn hook populates tokens, duration, and failures metrics."""
        ctx = HookContext(
            event="post_turn",
            tenant_id="test_tenant",
            conversation_id="test_session",
            user_id="test_user",
            profile="test_profile",
            payload={
                "duration": 5.4,
                "status": "error",
                "error_type": "ValueError",
                "prompt_tokens": 150,
                "completion_tokens": 50,
                "reasoning_tokens": 10,
                "model": "qwen-3b",
                "llm_calls": 3,
            },
        )

        asyncio.run(hook_registry.dispatch("post_turn", ctx))

        # Check LLM tokens
        prompt_val = metrics.aion_llm_tokens_total.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="prompt",
        )._value.get()
        self.assertEqual(prompt_val, 150)

        completion_val = metrics.aion_llm_tokens_total.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="completion",
        )._value.get()
        self.assertEqual(completion_val, 50)

        reasoning_val = metrics.aion_llm_tokens_total.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="reasoning",
        )._value.get()
        self.assertEqual(reasoning_val, 10)

        # Check LLM turn tokens
        turn_prompt_val = metrics.aion_llm_turn_tokens.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="prompt",
        )._value.get()
        self.assertEqual(turn_prompt_val, 150)

        turn_completion_val = metrics.aion_llm_turn_tokens.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="completion",
        )._value.get()
        self.assertEqual(turn_completion_val, 50)

        turn_reasoning_val = metrics.aion_llm_turn_tokens.labels(
            tenant_id="test_tenant",
            profile="test_profile",
            model="qwen-3b",
            token_type="reasoning",
        )._value.get()
        self.assertEqual(turn_reasoning_val, 10)

        # Check LLM turn calls
        turn_calls_val = metrics.aion_llm_turn_calls.labels(
            tenant_id="test_tenant", profile="test_profile"
        )._value.get()
        self.assertEqual(turn_calls_val, 3)

        # Check failures
        fail_val = metrics.aion_agent_failures_total.labels(
            tenant_id="test_tenant", profile="test_profile", error_type="ValueError"
        )._value.get()
        self.assertEqual(fail_val, 1)

    def test_mcp_health_metric_dynamic_initialization(self):
        """Verify that mcp health metric is dynamically initialized to 0 when warm_session or session_context is called."""
        from src.mcp_manager import mcp_manager

        # Test warm_session initialization
        test_mcp_name = "test_warm_session_mcp"

        # Ensure it's not already in the metrics
        label_tuple = (test_mcp_name,)
        if label_tuple in metrics.aion_mcp_server_healthy.prom_metric._metrics:
            del metrics.aion_mcp_server_healthy.prom_metric._metrics[label_tuple]

        # Call warm_session for a dummy session with this MCP name
        async def run_warm_session():
            await mcp_manager.warm_session(
                chat_session_id="test_session_id",
                server_names=[test_mcp_name],
            )

        asyncio.run(run_warm_session())

        # Check that the metric has been initialized and exists in the registry map
        self.assertIn(label_tuple, metrics.aion_mcp_server_healthy.prom_metric._metrics)
        val = metrics.aion_mcp_server_healthy.labels(
            mcp_server=test_mcp_name
        )._value.get()
        self.assertEqual(val, 0)

        # Test session_context initialization
        test_ctx_mcp_name = "test_session_context_mcp"
        label_tuple_ctx = (test_ctx_mcp_name,)
        if label_tuple_ctx in metrics.aion_mcp_server_healthy.prom_metric._metrics:
            del metrics.aion_mcp_server_healthy.prom_metric._metrics[label_tuple_ctx]

        # Mock mcp_manager.get_server_config to avoid raising ValueError
        orig_get_server_config = mcp_manager.get_server_config
        # We simulate that the server config is not found (None) to test unregistered/missing configs
        mcp_manager.get_server_config = lambda name: (
            None if name == test_ctx_mcp_name else orig_get_server_config(name)
        )

        async def run_session_context():
            try:
                async with mcp_manager.session_context(test_ctx_mcp_name):
                    pass
            except Exception:
                # Expect ValueError because it's not in the registry, which is fine since initialization occurs before that
                pass

        asyncio.run(run_session_context())
        mcp_manager.get_server_config = orig_get_server_config

        # Check that the metric has been initialized and exists in the registry map
        self.assertIn(
            label_tuple_ctx, metrics.aion_mcp_server_healthy.prom_metric._metrics
        )
        val_ctx = metrics.aion_mcp_server_healthy.labels(
            mcp_server=test_ctx_mcp_name
        )._value.get()
        self.assertEqual(val_ctx, 0)

    def test_mcp_health_metric_multi_session_and_profile_switch(self):
        """Test global instance counting and proactive old worker release on profile switch."""
        from src.mcp_manager import mcp_manager

        # 1. Test global instance counting
        srv_name = "test_counting_mcp"

        # Reset metric
        label_tuple = (srv_name,)
        if label_tuple in metrics.aion_mcp_server_healthy.prom_metric._metrics:
            del metrics.aion_mcp_server_healthy.prom_metric._metrics[label_tuple]

        # Manually increment twice (representing two sessions starting the worker)
        async def do_increments():
            await mcp_manager._increment_active_server(srv_name)
            await mcp_manager._increment_active_server(srv_name)

        asyncio.run(do_increments())

        # Health should be 1
        val = metrics.aion_mcp_server_healthy.labels(mcp_server=srv_name)._value.get()
        self.assertEqual(val, 1)
        self.assertEqual(mcp_manager._active_servers.get(srv_name), 2)

        # Decrement once (one session exits)
        asyncio.run(mcp_manager._decrement_active_server(srv_name))

        # Health should still be 1 (since 1 session is still active)
        val = metrics.aion_mcp_server_healthy.labels(mcp_server=srv_name)._value.get()
        self.assertEqual(val, 1)
        self.assertEqual(mcp_manager._active_servers.get(srv_name), 1)

        # Decrement second time (last session exits)
        asyncio.run(mcp_manager._decrement_active_server(srv_name))

        # Health should drop to 0
        val = metrics.aion_mcp_server_healthy.labels(mcp_server=srv_name)._value.get()
        self.assertEqual(val, 0)
        self.assertEqual(mcp_manager._active_servers.get(srv_name), 0)

        # 2. Test profile switch shutdown
        session_id = "test_profile_switch_session"
        mcp_a = "mcp_alpha"
        mcp_b = "mcp_beta"

        # Mock get_server_config and _is_stdio_server so warm_session tries to start it
        orig_get_config = mcp_manager.get_server_config
        orig_is_stdio = mcp_manager._is_stdio_server

        mcp_manager.get_server_config = lambda name: (
            {"type": "stdio", "command": "invalid_command_xyz_123", "args": []}
            if name in (mcp_a, mcp_b)
            else orig_get_config(name)
        )
        mcp_manager._is_stdio_server = lambda name: (
            True if name in (mcp_a, mcp_b) else orig_is_stdio(name)
        )

        # Warm session with mcp_alpha
        async def warm_a():
            # Mock worker creation to avoid spawning a real subprocess which would block
            from src.mcp_manager import MCPStdioWorker

            worker_mock = MagicMock(spec=MCPStdioWorker)
            worker_mock.start = AsyncMock()
            worker_mock.shutdown = AsyncMock()

            # Put worker in pool for session_id (same session)
            mcp_manager._pool[(session_id, mcp_a)] = worker_mock

            # Put worker in pool for another session under the same user but different profile
            other_session_id = "test_other_session"
            worker_mock_other = MagicMock(spec=MCPStdioWorker)
            worker_mock_other.start = AsyncMock()
            worker_mock_other.shutdown = AsyncMock()
            mcp_manager._pool[(other_session_id, mcp_a)] = worker_mock_other
            mcp_manager._session_ctx[other_session_id] = (
                "plane_assistant",
                "default",
                "default",
            )

            # Switch profile to mcp_beta under new session with generic_assistant
            await mcp_manager.warm_session(
                chat_session_id=session_id,
                server_names=[mcp_b],
                profile_slug="generic_assistant",
                user_id="default",
                tenant_id="default",
            )

            # Verify that both workers were shut down
            worker_mock.shutdown.assert_called_once()
            worker_mock_other.shutdown.assert_called_once()
            self.assertNotIn((session_id, mcp_a), mcp_manager._pool)
            self.assertNotIn((other_session_id, mcp_a), mcp_manager._pool)

        asyncio.run(warm_a())

        # Restore mocks
        mcp_manager.get_server_config = orig_get_config
        mcp_manager._is_stdio_server = orig_is_stdio

    def test_turn_duration_kpi_media_delle_medie(self):
        """Verify turn duration KPI is the mean of profile averages regardless of profile filter, and profile breakdown shows per-profile averages."""
        from src.api import metrics_api
        from src.api.metrics_api import get_metrics_overview

        # Mock _query_prometheus to force local fallback testing
        orig_query_prom = metrics_api._query_prometheus
        metrics_api._query_prometheus = lambda *args, **kwargs: None

        try:
            # Observe turn duration for profile_dur_a (10.0s) and profile_dur_b (20.0s)
            metrics.aion_turn_duration_seconds.labels(
                tenant_id="default", profile="profile_dur_a"
            ).observe(10.0)

            metrics.aion_turn_duration_seconds.labels(
                tenant_id="default", profile="profile_dur_b"
            ).observe(20.0)

            # Call get_metrics_overview passing profile filter "profile_dur_a"
            overview = get_metrics_overview(profile="profile_dur_a", time_range="all")

            # Global KPI avg_turn_duration_seconds should be (10.0 + 20.0) / 2 = 15.0s, un-influenced by profile filter
            self.assertAlmostEqual(overview.avg_turn_duration_seconds, 15.0, places=2)

            # Check breakdown in profile_metrics list
            prof_a_metric = next(
                (p for p in overview.profile_metrics if p.profile == "profile_dur_a"),
                None,
            )
            prof_b_metric = next(
                (p for p in overview.profile_metrics if p.profile == "profile_dur_b"),
                None,
            )

            self.assertIsNotNone(prof_a_metric)
            self.assertIsNotNone(prof_b_metric)
            self.assertAlmostEqual(
                prof_a_metric.avg_turn_duration_seconds, 10.0, places=2
            )
            self.assertAlmostEqual(
                prof_b_metric.avg_turn_duration_seconds, 20.0, places=2
            )
        finally:
            metrics_api._query_prometheus = orig_query_prom

    def test_user_metrics_breakdown_and_user_filter(self):
        """Verify user_metrics breakdown per user and user_id filtering in get_metrics_overview."""
        from src.api import metrics_api
        from src.api.metrics_api import get_metrics_overview

        orig_query_prom = metrics_api._query_prometheus
        metrics_api._query_prometheus = lambda *args, **kwargs: None

        try:
            # Record tokens for user_test_1 on profile_a and profile_b
            metrics.aion_llm_tokens_total.labels(
                tenant_id="user_test_1",
                profile="profile_a",
                model="gpt-4",
                token_type="prompt",
            ).inc(100)
            metrics.aion_llm_tokens_total.labels(
                tenant_id="user_test_1",
                profile="profile_b",
                model="gpt-4",
                token_type="completion",
            ).inc(50)

            # Record tokens for user_test_2 on profile_a
            metrics.aion_llm_tokens_total.labels(
                tenant_id="user_test_2",
                profile="profile_a",
                model="gpt-4",
                token_type="prompt",
            ).inc(200)

            # Record tool calls for user_test_1 on profile_a
            metrics.aion_tool_calls_total.labels(
                tenant_id="user_test_1",
                profile="profile_a",
                tool_name="web_search",
                mcp_server="native",
                status="ok",
            ).inc(3)

            # Get overview without user filter
            overview = get_metrics_overview(time_range="all")
            self.assertTrue(hasattr(overview, "user_metrics"))

            u1_metric = next(
                (u for u in overview.user_metrics if u.user_id == "user_test_1"), None
            )
            u2_metric = next(
                (u for u in overview.user_metrics if u.user_id == "user_test_2"), None
            )
            self.assertIsNotNone(u1_metric)
            self.assertIsNotNone(u2_metric)
            self.assertEqual(u1_metric.total_tokens, 150)
            self.assertEqual(u2_metric.total_tokens, 200)

            # Check user_test_1 profile breakdown (profile_a and profile_b)
            self.assertEqual(len(u1_metric.profile_breakdown), 2)
            prof_a = next(
                (p for p in u1_metric.profile_breakdown if p.profile == "profile_a"),
                None,
            )
            self.assertIsNotNone(prof_a)
            self.assertEqual(prof_a.prompt_tokens, 100)
            self.assertEqual(prof_a.total_tool_calls, 3)
            self.assertEqual(len(prof_a.tools_breakdown), 1)
            self.assertEqual(prof_a.tools_breakdown[0].tool_name, "web_search")
            self.assertEqual(prof_a.tools_breakdown[0].call_count, 3)

            # Filter overview by user_id="user_test_1"
            overview_u1 = get_metrics_overview(user_id="user_test_1", time_range="all")
            self.assertEqual(overview_u1.total_tokens, 150)
            self.assertEqual(len(overview_u1.user_metrics), 1)
            self.assertEqual(overview_u1.user_metrics[0].user_id, "user_test_1")
        finally:
            metrics_api._query_prometheus = orig_query_prom


if __name__ == "__main__":
    unittest.main()
