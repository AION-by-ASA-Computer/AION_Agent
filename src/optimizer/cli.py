import optuna
import os
import argparse
from .objective import aion_agent_objective

def main():
    parser = argparse.ArgumentParser(description="AION Agent Optuna Optimizer")
    parser.add_argument("--trials", type=int, default=10, help="Number of trials to run")
    parser.add_argument("--study-name", type=str, default="aion-agent-optimization", help="Optuna study name")
    parser.add_argument("--storage", type=str, default="sqlite:///data/optuna.db", help="Optuna storage URL")
    
    args = parser.parse_args()
    
    os.makedirs("data", exist_ok=True)
    
    study = optuna.create_study(
        study_name=args.study_name,
        storage=args.storage,
        direction="maximize",
        load_if_exists=True
    )
    
    print(f"Starting Optuna optimization: {args.study_name}")
    print(f"Trials: {args.trials}, Storage: {args.storage}")
    
    study.optimize(aion_agent_objective, n_trials=args.trials)
    
    print("\nOptimization finished!")
    print(f"Best trial: {study.best_trial.number}")
    print(f"Best score: {study.best_trial.value}")
    print("Best hyperparameters:")
    for key, value in study.best_trial.params.items():
        print(f"    {key}: {value}")
        
    print("\nTo view the dashboard, run: optuna-dashboard " + args.storage)

if __name__ == "__main__":
    main()
