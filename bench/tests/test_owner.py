import asyncio

from keryx_bench.owner import Answer, KeywordMatcher, OwnerScript, StandIn

SCRIPT = OwnerScript(
    autonomy="Commit locally on your own branch only. Do not push.",
    answers=(Answer(about="function name", answer="Keep the name add."),),
    default="No preference. Make the call and log it.",
)


def ask(*questions):
    return [{"question": q, "header": "Q", "multiSelect": False,
             "options": [{"label": "A", "description": ""}, {"label": "B", "description": ""}]}
            for q in questions]


async def yes(text):
    return True


async def no(text):
    return False


def test_a_scripted_question_gets_its_answer():
    s = StandIn(SCRIPT, KeywordMatcher())
    answers = asyncio.run(s.answer(ask("Which function name should I use?")))
    assert answers == {"Which function name should I use?": "Keep the name add."}


def test_an_unscripted_question_gets_autonomy_and_default():
    s = StandIn(SCRIPT, KeywordMatcher())
    answers = asyncio.run(s.answer(ask("Should I also refactor the module?")))
    assert answers["Should I also refactor the module?"] == SCRIPT.autonomy + " " + SCRIPT.default


def test_one_call_with_several_questions_is_one_interruption():
    s = StandIn(SCRIPT, KeywordMatcher())
    asyncio.run(s.answer(ask("Which function name?", "Anything else?")))
    assert s.interruptions == 1


def test_a_final_report_gets_no_reply():
    s = StandIn(SCRIPT, KeywordMatcher())
    assert asyncio.run(s.on_stop("Done: add fixed, tests pass.", no)) is None
    assert s.interruptions == 0


def test_a_stop_that_asks_for_approval_gets_the_autonomy_answer():
    s = StandIn(SCRIPT, KeywordMatcher())
    reply = asyncio.run(s.on_stop("Should I push the branch and open a PR?", yes))
    assert reply == SCRIPT.autonomy + " " + SCRIPT.default
    assert s.interruptions == 1


def test_a_report_without_a_question_mark_is_never_judged_a_question():
    # Seen: a cheap judge called a final report a question; the run lost a turn and counted an interruption.
    asked = []

    async def eager_judge(text):
        asked.append(text)
        return True

    s = StandIn(SCRIPT, KeywordMatcher())
    report = "Fixed and committed. Decisions you may want to change: 1. a numeric year becomes None."
    assert asyncio.run(s.on_stop(report, eager_judge)) is None
    assert s.interruptions == 0 and asked == []
