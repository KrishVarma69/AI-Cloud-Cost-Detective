import AuthForm from "../components/AuthForm";
import { useAuth } from "../auth";

export default function Signup() {
  const { signup } = useAuth();
  return <AuthForm mode="signup" onSubmit={signup} />;
}
