import { apiGet, apiPost } from "@/lib/api";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  is_active: boolean;
  created_at: string;
  default_workspace_id: string | null;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  password: string;
  full_name?: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export async function login(credentials: LoginCredentials): Promise<AuthResponse> {
  const formData = new URLSearchParams();
  formData.append("username", credentials.email);
  formData.append("password", credentials.password);

  return apiPost<AuthResponse>("/api/v1/auth/login", formData, {
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
}

export async function register(data: RegisterData): Promise<User> {
  return apiPost<User>("/api/v1/auth/register", data);
}

export async function requestPasswordReset(email: string): Promise<{ message: string }> {
  return apiPost<{ message: string }>("/api/v1/auth/password-reset/request", { email });
}

export async function confirmPasswordReset(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return apiPost<{ message: string }>("/api/v1/auth/password-reset/confirm", {
    token,
    new_password: newPassword,
  });
}

export async function getCurrentUser(): Promise<User> {
  return apiGet<User>("/api/v1/auth/me");
}

export async function refreshToken(): Promise<AuthResponse> {
  // Refresh token is sent automatically via httpOnly cookie
  return apiPost<AuthResponse>("/api/v1/auth/refresh");
}
