import { createContext, useContext } from "react";
import type { ReactNode } from "react";

const ProjectRootContext = createContext<string | null>(null);

export function ProjectRootProvider({
  projectRoot,
  children,
}: {
  projectRoot: string;
  children: ReactNode;
}) {
  return (
    <ProjectRootContext.Provider value={projectRoot}>
      {children}
    </ProjectRootContext.Provider>
  );
}

export function useProjectRootOptional(): string | null {
  return useContext(ProjectRootContext);
}
