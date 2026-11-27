"""Scripted races against the real websocket server (instructor feedback).

Race 1 is a worked example written by Claude; races 2-4 are hand-written.
"""

import asyncio

from tests.harness import Client, race_server


def test_simultaneous_winning_guesses():
    """Two players send the winning word at the same moment: both rank first,
    and each gets exactly one results message."""

    async def race():
        async with race_server(secret="crane", players=2) as url:
            alice = await Client.join(url, "alice")
            bob = await Client.join(url, "bob")
            await alice.wait_for("start")
            await bob.wait_for("start")

            # Fire both guesses without waiting for either reply.
            a, b = await asyncio.gather(alice.guess("crane"), bob.guess("crane"))
            assert a["pattern"] == b["pattern"] == 242

            for player in (alice, bob):
                results = await player.wait_for("results")
                places = {r["name"]: r["place"] for r in results["ranking"]}
                assert places == {"alice": 1, "bob": 1}
                await asyncio.wait_for(player.closed.wait(), 2)
                assert player.count("results") == 1

    asyncio.run(race())
