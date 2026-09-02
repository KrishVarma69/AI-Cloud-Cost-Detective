import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError } from "../api";

type Props = {
  mode: "login" | "signup";
  onSubmit: (email: string, password: string) => Promise<void>;
};

export default function AuthForm({ mode, onSubmit }: Props) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onSubmit(email.trim(), password);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <div className="mb-8 text-center">
        <div className="text-2xl font-bold text-white">
          <span className="text-brand">◆</span> Cost Detective
        </div>
        <p className="mt-1 text-sm text-gray-500">
          AI-powered AWS cost investigation
        </p>
      </div>

      <form
        onSubmit={submit}
        className="space-y-4 rounded-xl border border-white/10 bg-[#0d131a] p-6"
      >
        <h1 className="text-lg font-semibold text-white">
          {isSignup ? "Create your account" : "Sign in"}
        </h1>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-white/10 bg-[#111820] px-3 py-2 text-sm text-white outline-none focus:border-brand"
            placeholder="you@example.com"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-white/10 bg-[#111820] px-3 py-2 text-sm text-white outline-none focus:border-brand"
            placeholder="At least 8 characters"
          />
        </label>

        {error && (
          <p className="rounded-md border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-brand px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-brand-dark disabled:opacity-50"
        >
          {busy ? "Please wait…" : isSignup ? "Sign up" : "Sign in"}
        </button>

        <p className="text-center text-xs text-gray-500">
          {isSignup ? (
            <>
              Already have an account?{" "}
              <Link to="/login" className="text-brand hover:underline">
                Sign in
              </Link>
            </>
          ) : (
            <>
              No account?{" "}
              <Link to="/signup" className="text-brand hover:underline">
                Sign up
              </Link>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
