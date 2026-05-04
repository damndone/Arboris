import { useOutletContext, useParams } from "react-router-dom";
import { RunResultView } from "./runResult";

type AppContextValue = {
  projectRoot: string;
  setError: (msg: string | null) => void;
};

export function RunDetailRoute() {
  const { runId } = useParams();
  const { projectRoot, setError } = useOutletContext<AppContextValue>();

  if (!projectRoot) {
    return (
      <section className="panel">
        <p className="muted">Missing project_root.</p>
      </section>
    );
  }

  if (!runId) {
    return (
      <section className="panel">
        <p className="muted">Missing run ID.</p>
      </section>
    );
  }

  return (
    <RunResultView
      projectRoot={projectRoot}
      runId={runId}
      onError={(message) => setError(message)}
    />
  );
}
