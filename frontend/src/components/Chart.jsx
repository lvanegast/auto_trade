import React, { useEffect, useRef } from 'react';
import { createChart } from 'lightweight-charts';

export default function Chart({ statusData }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);
  const candleSeriesRef = useRef(null);
  const comparisonSeriesRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    try {
      const chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth || 800,
        height: 380,
        layout: {
          background: { color: '#161a1e' },
          textColor: '#848e9c',
        },
        grid: {
          vertLines: { color: '#20262d' },
          horzLines: { color: '#20262d' },
        },
        crosshair: {
          mode: 0,
        },
        leftPriceScale: {
          visible: true,
        },
        rightPriceScale: {
          visible: true,
        },
        timeScale: {
          borderColor: '#242c35',
          timeVisible: true,
          secondsVisible: false,
        },
      });

      chartRef.current = chart;

      if (typeof chart.addCandlestickSeries === 'function') {
        candleSeriesRef.current = chart.addCandlestickSeries({
          upColor: '#02c076',
          downColor: '#f84960',
          borderVisible: false,
          wickUpColor: '#02c076',
          wickDownColor: '#f84960',
          priceScaleId: 'right',
        });
      }

      if (typeof chart.addLineSeries === 'function') {
        comparisonSeriesRef.current = chart.addLineSeries({
          color: '#ff9900',
          lineWidth: 2,
          priceLineVisible: false,
          title: 'COBERTA',
          priceScaleId: 'left',
        });
      }
    } catch (e) {
      console.error('[Chart Init Error]', e);
    }

    const handleResize = () => {
      if (chartRef.current && chartContainerRef.current) {
        try {
          chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth || 800 });
        } catch (_) {}
      }
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chartRef.current) {
        try {
          chartRef.current.remove();
        } catch (_) {}
      }
    };
  }, []);

  // Actualizar datos del gráfico
  useEffect(() => {
    if (!statusData) return;

    if (candleSeriesRef.current && statusData.price_history && statusData.price_history.length > 0) {
      const formatted = statusData.price_history.map((c) => ({
        time: Math.floor(new Date(c.timestamp).getTime() / 1000),
        open: parseFloat(c.open),
        high: parseFloat(c.high),
        low: parseFloat(c.low),
        close: parseFloat(c.close),
      })).filter((c) => !isNaN(c.time) && !isNaN(c.close)).sort((a, b) => a.time - b.time);

      try {
        candleSeriesRef.current.setData(formatted);
      } catch (err) {
        console.error('[Candle Series Error]', err);
      }
    }

    if (comparisonSeriesRef.current && statusData.comparison_history && statusData.comparison_history.length > 0) {
      const formattedComp = statusData.comparison_history.map((c) => ({
        time: Math.floor(new Date(c.timestamp).getTime() / 1000),
        value: parseFloat(c.close || c.price),
      })).filter((c) => !isNaN(c.time) && !isNaN(c.value)).sort((a, b) => a.time - b.time);

      try {
        comparisonSeriesRef.current.setData(formattedComp);
      } catch (err) {
        console.error('[Comp Series Error]', err);
      }
    }
  }, [statusData]);

  const isPredictionMarket = statusData?.feeder_type === 'kalshi' || statusData?.feeder_type === 'polymarket';
  const rawProb = statusData?.teorical_probability ?? 0.5;
  const prob = rawProb <= 1.0 ? rawProb * 100 : 50.0;

  return (
    <div className="chart-panel" style={{ position: 'relative', width: '100%', flex: 1, minHeight: '380px', background: '#161a1e' }}>
      <div className="chart-header" style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 15px', background: '#181a20', borderBottom: '1px solid #242c35' }}>
        <div>
          <strong style={{ fontSize: '16px', color: '#fff', marginRight: '10px' }}>{statusData?.symbol || 'BTC/USD'}</strong>
          <span style={{ fontSize: '11px', color: '#848e9c', background: '#20262d', padding: '2px 6px', borderRadius: '4px' }}>
            {(statusData?.feeder_type || 'ALPACA').toUpperCase()} FEED
          </span>
        </div>
        <div style={{ fontSize: '12px', color: '#848e9c', display: 'flex', gap: '15px' }}>
          <span>P. Teórica: <strong style={{ color: '#00e6ff' }}>{prob.toFixed(1)}%</strong></span>
          <span>Edge: <strong style={{ color: '#02c076' }}>{((statusData?.edge || 0) * 100).toFixed(2)}%</strong></span>
          <span>Kelly: <strong style={{ color: '#ff9900' }}>{((statusData?.kelly_recommendation || 0) * 100).toFixed(2)}%</strong></span>
        </div>
      </div>

      <div ref={chartContainerRef} style={{ width: '100%', height: '360px' }} />

      {/* Tarjeta flotante de dial de probabilidad para mercados de predicción */}
      {isPredictionMarket && (
        <div
          style={{
            position: 'absolute',
            top: '55px',
            right: '20px',
            width: '130px',
            padding: '10px',
            background: 'rgba(22, 26, 30, 0.85)',
            backdropFilter: 'blur(6px)',
            border: '1px solid #2d3139',
            borderRadius: '8px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            zIndex: 10,
          }}
        >
          <span style={{ fontSize: '10px', color: '#848e9c', fontWeight: 600, marginBottom: '6px' }}>PROBABILIDAD YES</span>
          <div style={{ fontSize: '20px', fontWeight: 700, color: '#02c076' }}>{prob.toFixed(1)}%</div>
          <div style={{ width: '100%', height: '4px', background: '#f84960', borderRadius: '2px', marginTop: '6px', overflow: 'hidden' }}>
            <div style={{ width: `${prob}%`, height: '100%', background: '#02c076' }} />
          </div>
        </div>
      )}
    </div>
  );
}
