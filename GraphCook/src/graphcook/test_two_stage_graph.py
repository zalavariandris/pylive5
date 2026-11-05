import unittest
import numpy as np
from two_stage_graph import (
    Context, Node, Engine, Planner, Executor, ReadVideo, TemporalBlend,
    blur_op, gain_op, Video,
)


class TwoStageTests(unittest.TestCase):
    def test_planning_expands_frames_and_never_computes(self):
        class CountingRead(ReadVideo):
            def __init__(self):
                super().__init__(frame_count=10)
                self.calls = 0
            def compute(self, frame_count):
                self.calls += 1
                return super().compute(frame_count)
        read = CountingRead()
        root = gain_op(source=blur_op(source=TemporalBlend(read, 3), radius=1), factor=2)
        plan = Planner().build(root, Context(frames={5}))
        self.assertEqual(plan.requests[read].frames, frozenset({3, 4, 5}))
        self.assertEqual(read.calls, 0)
        result = Executor().execute(plan, root)
        self.assertEqual(read.calls, 1)
        self.assertEqual(set(result.frames), {5})

    def test_shared_upstream_merges_requests_then_computes_once(self):
        class Source(Node):
            def __init__(self):
                super().__init__()
                self.calls = 0
                self.computed_frames = None
            def compute(self):
                self.calls += 1
                self.computed_frames = Context.current().frames
                return Video({f: np.full((1, 1, 1), f) for f in self.computed_frames})

        class Shift(Node):
            def __init__(self, source, offset):
                super().__init__(source=source, offset=offset)
            def request(self, ctx):
                return {"source": ctx.with_frames(f + self.params['offset'] for f in ctx.frames)}
            def compute(self, source, offset):
                return Video({f: source.frames[f + offset] for f in Context.current().frames})

        class Add(Node):
            def __init__(self, left, right):
                super().__init__(left=left, right=right)
            def compute(self, left, right):
                return Video({f: left.frames[f] + right.frames[f] for f in left.frames})

        src = Source()
        root = Add(Shift(src, -1), Shift(src, +1))
        result = Engine().evaluate(root, Context(frames={5}))
        self.assertEqual(src.calls, 1)
        self.assertEqual(src.computed_frames, frozenset({4, 6}))
        self.assertEqual(result.frames[5].item(), 10)

    def test_no_context_operator_and_all_frames(self):
        source = ReadVideo(5)
        root = gain_op(source=source, factor=3)
        result = Engine().evaluate(root, Context())
        self.assertEqual(set(result.frames), set(range(5)))

    def test_cycle_detected(self):
        class Forward(Node):
            def compute(self, source):
                return source
        a, b = Forward(), Forward()
        a.inputs['source'] = b
        b.inputs['source'] = a
        with self.assertRaisesRegex(ValueError, 'cycle'):
            Planner().build(a, Context(frames={1}))

    def test_active_context_restored_after_failure(self):
        class Fail(Node):
            def compute(self):
                self_ctx = Context.current()
                assert self_ctx.frames == {2}
                raise ValueError('broken')
        with self.assertRaisesRegex(ValueError, 'broken'):
            Engine().evaluate(Fail(), Context(frames={2}))
        with self.assertRaises(RuntimeError):
            Context.current()

    def test_default_context_is_inherited(self):
        class Identity(Node):
            def __init__(self, source):
                super().__init__(source=source)
            def compute(self, source):
                return source
        read = ReadVideo(6)
        result = Engine().evaluate(Identity(read), Context(frames={3}))
        self.assertEqual(set(result.frames), {3})

if __name__ == '__main__':
    unittest.main()
