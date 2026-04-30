export type ProjectResponse = {
  project_root: string;
};

export type RunResponse = {
  run_id: string;
  status: string;
};

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createProject(
  parent: string,
  name: string
): Promise<ProjectResponse> {
  const response = await fetch("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parent, name })
  });
  return readJson<ProjectResponse>(response);
}

export async function runWorkflow(
  projectRoot: string,
  mode: string,
  y: string,
  x: string,
  file: File
): Promise<RunResponse> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("mode", mode);
  form.append("y", y);
  form.append("x", x);
  form.append("file", file);
  const response = await fetch("/runs", { method: "POST", body: form });
  return readJson<RunResponse>(response);
}
