import AuthForm from "../components/AuthForm";
import { useAuth } from "../auth";

export default function Login() {
  const { login } = useAuth();
  return <AuthForm mode="login" onSubmit={login} />;
}
