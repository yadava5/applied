/**
 * Seed schema — hand-authored minimal TypeScript bindings for the JobTracker
 * FastAPI backend. Covers only the endpoints we need today so downstream
 * screens (C11–C16) can compile against a typed client without a live
 * backend running in CI.
 *
 * Run `pnpm api:gen` (or `pnpm api:gen:local` against a local `uvicorn`)
 * when the backend is reachable to regenerate from the live openapi.json.
 * The generated file will OVERWRITE this one — that is the desired flow.
 *
 * Shape mirrors `openapi-typescript`'s output: a single `paths` interface
 * keyed by URL, each with per-method operation objects exposing
 * `parameters`, `requestBody`, and `responses`. `openapi-fetch`'s
 * generic parameter is `paths`, so consumers import this default export
 * and pass it through to `createClient<paths>`.
 *
 * Source of truth for endpoint shapes: docs/API_SPEC.md and
 * backend/jobtracker/main_cloud.py.
 */

export interface paths {
  "/auth/me": {
    get: operations["get_auth_me"];
  };
  "/health": {
    get: operations["get_health"];
  };
  "/applications": {
    get: operations["list_applications"];
    post: operations["create_application"];
  };
}

export interface components {
  schemas: {
    AuthMeResponse: {
      user_id: string;
      authenticated: boolean;
    };
    HealthResponse: {
      status: string;
      database?: string | null;
      accounts?: Record<string, unknown> | null;
      classifier?: Record<string, unknown> | null;
    };
    Application: {
      id: number;
      user_id: string;
      company: string;
      position: string;
      status: string;
      notes: string | null;
      created_at: string;
    };
    ApplicationListResponse: {
      applications: components["schemas"]["Application"][];
      total: number;
    };
    ApplicationCreate: {
      company: string;
      position: string;
      status?: string;
      notes?: string | null;
    };
  };
}

export interface operations {
  get_auth_me: {
    responses: {
      200: {
        content: {
          "application/json": components["schemas"]["AuthMeResponse"];
        };
      };
      401: {
        content: {
          "application/json": { detail: string };
        };
      };
    };
  };
  get_health: {
    responses: {
      200: {
        content: {
          "application/json": components["schemas"]["HealthResponse"];
        };
      };
    };
  };
  list_applications: {
    parameters: {
      query?: {
        page?: number;
        page_size?: number;
        status?: string;
        company?: string;
        search?: string;
      };
    };
    responses: {
      200: {
        content: {
          "application/json": components["schemas"]["ApplicationListResponse"];
        };
      };
      401: {
        content: {
          "application/json": { detail: string };
        };
      };
    };
  };
  create_application: {
    requestBody: {
      content: {
        "application/json": components["schemas"]["ApplicationCreate"];
      };
    };
    responses: {
      200: {
        content: {
          "application/json": components["schemas"]["Application"];
        };
      };
      401: {
        content: {
          "application/json": { detail: string };
        };
      };
      422: {
        content: {
          "application/json": { detail: unknown };
        };
      };
    };
  };
}

export type webhooks = Record<string, never>;
