/**
 * Types of the backend API, generated from its OpenAPI document
 * (scripts/generate_api_types.py -> generated/api-schema.ts).
 *
 * Use `Schema<"RunDetail">` for a named shape, and
 * `ResponseOf<"/agent/sessions/{session_id}/turns", "post">` /
 * `RequestOf<...>` for what one operation returns and accepts. Hand-written
 * copies of server shapes drift silently; a backend change to a declared
 * shape fails tests/test_api_types_drift.py until the file is regenerated.
 */
import type { components, paths } from "./generated/api-schema";

export type Schemas = components["schemas"];
export type Schema<K extends keyof Schemas> = Schemas[K];

type Method = "get" | "put" | "post" | "delete" | "patch";
type Path = keyof paths;

/** The methods a path declares. */
export type MethodOf<P extends Path> = {
  [M in Method]-?: undefined extends paths[P][M] ? never : M;
}[Method];

type Operation<P extends Path, M extends MethodOf<P>> = paths[P][M];
type Success<R> = R extends { 200: infer S } ? S : R extends { 201: infer S } ? S : never;
type Json<C> = C extends { content: { "application/json": infer T } } ? T : never;

/** The JSON body a successful call of this operation returns. */
export type ResponseOf<P extends Path, M extends MethodOf<P>> = Json<
  Success<Operation<P, M> extends { responses: infer R } ? R : never>
>;

/** The JSON body this operation accepts. */
export type RequestOf<P extends Path, M extends MethodOf<P>> = Json<
  NonNullable<Operation<P, M> extends { requestBody?: infer B } ? B : never>
>;
