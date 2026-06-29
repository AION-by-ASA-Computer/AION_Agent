const DBEditorEmbed = () => {
  const { url, height } = props;
  const frameHeight = Number(height) > 0 ? Number(height) : 720;

  if (!url) {
    return (
      <div className="p-4 text-sm text-red-400 border border-red-500/30 rounded-md">
        Missing DB editor URL.
      </div>
    );
  }

  return (
    <div className="w-full h-full">
      <iframe
        src={url}
        title="DB Editor"
        style={{
          width: "100%",
          height: `${frameHeight}px`,
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "8px",
          background: "transparent",
        }}
      />
    </div>
  );
};

export default DBEditorEmbed;

