import argparse
import asyncio
import sys

from src.benchmarks.general_agent import run_evaluation
from src.main import set_event_loop


def main():
    parser = argparse.ArgumentParser(description="AION Agent Evaluation Harness")
    parser.add_argument(
        "--dataset", type=str, required=True, help="Path al file JSON del dataset"
    )
    parser.add_argument(
        "--profile", type=str, default="aion_std", help="Profilo agente da valutare"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.8,
        help="Soglia minima di successo (0.0 - 1.0) per passare la CI",
    )

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    set_event_loop(loop)

    overall = loop.run_until_complete(
        run_evaluation(args.dataset, args.profile, args.threshold)
    )

    if overall < args.threshold:
        sys.exit(1)


if __name__ == "__main__":
    main()
