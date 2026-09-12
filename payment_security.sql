-- Run once in this project's Supabase SQL Editor. No existing paid flags are reset.
-- Prevent user-editable profiles from becoming a payment bypass.
BEGIN;
CREATE OR REPLACE FUNCTION public.protect_premium_status()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF current_user IN ('anon', 'authenticated') AND
     ((TG_OP = 'INSERT' AND NEW.is_premium IS TRUE) OR
      (TG_OP = 'UPDATE' AND NEW.is_premium IS DISTINCT FROM OLD.is_premium)) THEN
    RAISE EXCEPTION 'Premium access can only be updated by the payment server';
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS protect_premium_status ON public.profiles;
CREATE TRIGGER protect_premium_status BEFORE INSERT OR UPDATE ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.protect_premium_status();
COMMIT;
