const PresentationEmbed = () => {
  const { url, height } = props;
  if (!url) return <div className="p-3 text-red-400">Missing presentation URL.</div>;
  const h = Number(height) > 0 ? Number(height) : 720;
  return (
    <div className="w-full h-full">
      <iframe
        src={url}
        title="Presentation Preview"
        style={{
          width: "100%",
          height: `${h}px`,
          border: "1px solid rgba(255,255,255,.16)",
          borderRadius: "8px",
          background: "transparent",
        }}
      />
    </div>
  );
};

export default PresentationEmbed;

