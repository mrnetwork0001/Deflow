import { Audit } from "@/components/site/Audit";
import { CTA, Footer } from "@/components/site/Closing";
import { Desk } from "@/components/site/Desk";
import { Gate } from "@/components/site/Gate";
import { Hero } from "@/components/site/Hero";
import { Nav } from "@/components/site/chrome";
import { Problem } from "@/components/site/Problem";
import { Stack } from "@/components/site/Stack";
import { Thesis } from "@/components/site/Thesis";
import { Universe } from "@/components/site/Universe";

export default function Landing() {
  return (
    <>
      <Nav />
      <Hero />
      <Problem />
      <Thesis />
      <Desk />
      <Gate />
      <Universe />
      <Audit />
      <Stack />
      <CTA />
      <Footer />
    </>
  );
}
