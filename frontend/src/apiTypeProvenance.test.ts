// @vitest-environment node
/**
 * V1812-OPENAPI-TYPES: what the API client returns is typed by the backend.
 *
 * Every exported function of a module that calls the backend and returns a
 * Promise must resolve to types declared in generated/api-schema.ts (through
 * Schema / ResponseOf or aliases of them), or to plain values (text, Blob,
 * void). A shape written by hand in the client is reported: it drifts from
 * the server silently. The check is semantic -- the TypeScript checker follows
 * every alias -- so no list of type names is kept here.
 */
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

// Every client function returns backend-declared types (v1.8.12: 66 -> 0).
const HAND_WRITTEN_BASELINE = 0;

// Functions whose result the client composes itself (not a server response).
const CLIENT_COMPOSED: Record<string, string> = {
  "src/api.ts previewFile": "parses CSV/Excel in the browser; only SPSS/Stata rows come from /uploads/preview",
};

const FRONTEND = path.resolve(__dirname, "..");
const GENERATED = path.join(FRONTEND, "src", "generated") + path.sep;
const ALLOWED_LIB_TYPES = new Set(["Blob", "Response", "ArrayBuffer", "Date"]);

function program(): ts.Program {
  const configPath = path.join(FRONTEND, "tsconfig.json");
  const parsed = ts.getParsedCommandLineOfConfigFile(configPath, {}, {
    ...ts.sys,
    onUnRecoverableConfigFileDiagnostic: (diagnostic) => {
      throw new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"));
    },
  });
  if (!parsed) throw new Error("tsconfig.json could not be read");
  return ts.createProgram(parsed.fileNames, parsed.options);
}

function isClientModule(file: ts.SourceFile): boolean {
  const name = file.fileName;
  if (!name.startsWith(path.join(FRONTEND, "src") + path.sep)) return false;
  if (name.startsWith(GENERATED) || /\.test\.tsx?$/.test(name)) return false;
  return /\bfetch\(|\bapiUrl\(/.test(file.text);
}

function declaredIn(symbol: ts.Symbol | undefined): string[] {
  return (symbol?.declarations ?? []).map((declaration) => declaration.getSourceFile().fileName);
}

/** Why `type` is not backend-declared, or null when it is. */
function handWritten(checker: ts.TypeChecker, type: ts.Type, seen: Set<ts.Type>): string | null {
  if (seen.has(type)) return null;
  seen.add(type);
  if (type.flags & ts.TypeFlags.TypeParameter) return null; // generic plumbing: the caller picks the type
  if (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) return "untyped (any/unknown)";
  if (type.flags & (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike
    | ts.TypeFlags.Void | ts.TypeFlags.Undefined | ts.TypeFlags.Null | ts.TypeFlags.Never)) return null;
  if (type.isUnionOrIntersection()) {
    for (const part of type.types) {
      const reason = handWritten(checker, part, seen);
      if (reason) return reason;
    }
    return null;
  }
  if (checker.isArrayType(type) || checker.isTupleType(type)) {
    for (const element of checker.getTypeArguments(type as ts.TypeReference)) {
      const reason = handWritten(checker, element, seen);
      if (reason) return reason;
    }
    return null;
  }
  const symbol = type.aliasSymbol ?? type.getSymbol();
  const files = declaredIn(symbol);
  if (files.some((file) => file.startsWith(GENERATED))) return null;
  if (files.length > 0 && files.every(isLibrary)) {
    if (symbol && ALLOWED_LIB_TYPES.has(symbol.getName())) return null;
    // Record<string, X> and similar: judge by what they hold.
    const args = type.aliasTypeArguments ?? [];
    if (args.length === 0) return `library type ${symbol?.getName()}`;
    for (const arg of args) {
      const reason = handWritten(checker, arg, seen);
      if (reason) return reason;
    }
    return null;
  }
  // A local alias over backend shapes (Pick, Omit, an indexed access) is still
  // backend-declared: judge it by where each of its fields is declared.
  const properties = checker.getPropertiesOfType(type);
  const local = properties.find((property) => !declaredIn(property).some((file) => file.startsWith(GENERATED)));
  if (properties.length > 0 && !local) return null;
  const where = files[0] ? path.relative(FRONTEND, files[0]) : "an anonymous type";
  const field = local ? ` (field ${local.getName()})` : "";
  return `${checker.typeToString(type).slice(0, 80)} declared in ${where}${field}`;
}

function isLibrary(file: string): boolean {
  return file.includes(`${path.sep}node_modules${path.sep}`);
}

function promisedType(checker: ts.TypeChecker, signature: ts.Signature): ts.Type | null {
  const returned = checker.getReturnTypeOfSignature(signature);
  if (returned.getSymbol()?.getName() !== "Promise") return null;
  return checker.getTypeArguments(returned as ts.TypeReference)[0] ?? null;
}

function findings(): { found: string[]; exempted: Set<string> } {
  const built = program();
  const checker = built.getTypeChecker();
  const found: string[] = [];
  const exempted = new Set<string>();
  for (const file of built.getSourceFiles().filter(isClientModule)) {
    const moduleSymbol = checker.getSymbolAtLocation(file);
    for (const exported of moduleSymbol ? checker.getExportsOfModule(moduleSymbol) : []) {
      const declaration = exported.valueDeclaration;
      if (!declaration || declaration.getSourceFile() !== file) continue;
      const type = checker.getTypeOfSymbolAtLocation(exported, declaration);
      for (const signature of type.getCallSignatures()) {
        const promised = promisedType(checker, signature);
        if (!promised) continue;
        const name = `${path.relative(FRONTEND, file.fileName)} ${exported.getName()}`;
        if (name in CLIENT_COMPOSED) {
          exempted.add(name);
          continue;
        }
        const reason = handWritten(checker, promised, new Set());
        if (reason) found.push(`${path.relative(FRONTEND, file.fileName)} ${exported.getName()}: ${reason}`);
      }
    }
  }
  return { found: found.sort(), exempted };
}

describe("API client type provenance", () => {
  it("returns backend-declared types", () => {
    const { found, exempted } = findings();
    expect(Object.keys(CLIENT_COMPOSED).filter((name) => !exempted.has(name)), "stale exemptions").toEqual([]);
    expect(found.length, `hand-written client shapes:\n${found.join("\n")}`).toBe(HAND_WRITTEN_BASELINE);
  }, 120_000);
});
