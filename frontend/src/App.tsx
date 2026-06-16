import { useState } from "react";
import { api } from "./api";
import { Dashboard } from "./components/Dashboard";
import { DataManager } from "./components/DataManager";
import { EvaluationWorkspace } from "./components/EvaluationWorkspace";
import { Login } from "./components/Login";

type Screen = "dashboard" | "data" | "evaluation";

export function App() {
  const [authenticated, setAuthenticated] = useState(
    () => localStorage.getItem("sheldon-token") !== null,
  );
  const [screen, setScreen] = useState<Screen>("dashboard");
  const [evaluationId, setEvaluationId] = useState<string | null>(null);
  const [dashboardNotice, setDashboardNotice] = useState("");

  const openEvaluation = (id: string) => {
    setDashboardNotice("");
    setEvaluationId(id);
    setScreen("evaluation");
  };

  const showDashboard = (notice = "") => {
    setDashboardNotice(notice);
    setScreen("dashboard");
  };

  const logout = async () => {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    localStorage.removeItem("sheldon-token");
    setAuthenticated(false);
    setDashboardNotice("");
    setScreen("dashboard");
  };

  if (!authenticated) {
    return (
      <Login
        onSuccess={(token) => {
          localStorage.setItem("sheldon-token", token);
          setAuthenticated(true);
        }}
      />
    );
  }

  if (screen === "evaluation" && evaluationId) {
    return (
      <EvaluationWorkspace
        evaluationId={evaluationId}
        onBack={() => showDashboard()}
      />
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <button
          className="brand-lockup brand-button"
          onClick={() => showDashboard()}
          type="button"
        >
          <span className="brand-mark">S</span>
          <span>
            <strong>Sheldon</strong>
            <small>Evaluation Platform</small>
          </span>
        </button>
        <nav className="header-nav" aria-label="Primary navigation">
          <button
            className={screen === "dashboard" ? "nav-active" : ""}
            onClick={() => showDashboard()}
            type="button"
          >
            Evaluations
          </button>
          <button
            className={screen === "data" ? "nav-active" : ""}
            onClick={() => {
              setDashboardNotice("");
              setScreen("data");
            }}
            type="button"
          >
            Add data
          </button>
        </nav>
        <div className="header-user">
          <span className="avatar">E1</span>
          <span className="header-user-copy">
            <strong>Evaluator 1</strong>
            <small>Sheldon Academy</small>
          </span>
          <button className="button-ghost" onClick={logout} type="button">
            Log out
          </button>
        </div>
      </header>
      {screen === "dashboard" ? (
        <Dashboard notice={dashboardNotice} onOpenEvaluation={openEvaluation} />
      ) : (
        <DataManager
          onOpenEvaluation={openEvaluation}
          onShowDashboard={showDashboard}
        />
      )}
    </div>
  );
}
