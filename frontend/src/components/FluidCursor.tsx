'use client';

import { useEffect } from 'react';
import fluidCursor from '@/hooks/useFluidCursor';

const FluidCursor = () => {
  useEffect(() => {
    fluidCursor();
  }, []);

  return (
    <div className="fixed top-0 left-0 z-[90] w-screen h-screen pointer-events-none">
      <canvas id="fluid" className="w-full h-full" />
    </div>
  );
};

export default FluidCursor;
