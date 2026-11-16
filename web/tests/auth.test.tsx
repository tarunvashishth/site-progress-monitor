import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthForm } from "@/components/auth-form";

const signIn = vi.fn();
const signUp = vi.fn();
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { signInWithPassword: signIn, signUp } }) }));

describe("login form", () => {
  beforeEach(() => { signIn.mockReset(); signUp.mockReset(); });
  it("validates before calling Supabase", async () => {
    render(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "not-an-email");
    await userEvent.type(screen.getByLabelText("Password"), "longenough");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/valid email/);
    expect(signIn).not.toHaveBeenCalled();
  });
  it("shows a generic error on bad credentials (no account enumeration)", async () => {
    signIn.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    render(<AuthForm mode="login" />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpassword");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Incorrect email or password."));
  });
  it("registration sends no role and mentions client accounts", async () => {
    signUp.mockResolvedValue({ data: { session: null }, error: null });
    render(<AuthForm mode="register" />);
    expect(screen.getByText(/New accounts are client accounts/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "new@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "longenough");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));
    await waitFor(() => expect(signUp).toHaveBeenCalled());
    expect(JSON.stringify(signUp.mock.calls[0][0])).not.toMatch(/role/);
  });
});
