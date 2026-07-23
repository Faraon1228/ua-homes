import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../models/models.dart';
import '../services/file_helper.dart';

class StoryViewerScreen extends StatefulWidget {
  final Story story;

  const StoryViewerScreen({required this.story, super.key});

  @override
  State<StoryViewerScreen> createState() => _StoryViewerScreenState();
}

class _StoryViewerScreenState extends State<StoryViewerScreen> {
  VideoPlayerController? _videoController;
  bool _isVideoReady = false;

  @override
  void initState() {
    super.initState();
    if (widget.story.isVideo) {
      if (widget.story.videoPath != null) {
        final file = localFile(widget.story.videoPath!);
        if (file != null) {
          _videoController = VideoPlayerController.file(file as dynamic);
        }
      } else if (widget.story.videoUrl != null) {
        _videoController = VideoPlayerController.networkUrl(Uri.parse(widget.story.videoUrl!));
      }

      if (_videoController != null) {
        _videoController!.initialize().then((_) {
          if (!mounted) return;
          setState(() {
            _isVideoReady = true;
          });
          _videoController?.play();
        });
      }
    }
  }

  @override
  void dispose() {
    _videoController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: AppBar(
        title: Text(widget.story.title),
        backgroundColor: const Color(0xFF121212),
      ),
      body: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (widget.story.isVideo)
            Expanded(
              child: _isVideoReady && _videoController != null
                  ? Stack(
                      children: [
                        Center(
                          child: AspectRatio(
                            aspectRatio: _videoController!.value.aspectRatio,
                            child: VideoPlayer(_videoController!),
                          ),
                        ),
                        Positioned(
                          right: 16,
                          bottom: 16,
                          child: FloatingActionButton(
                            mini: true,
                            backgroundColor: const Color(0xFFDE0046),
                            onPressed: () {
                              setState(() {
                                if (_videoController?.value.isPlaying == true) {
                                  _videoController?.pause();
                                } else {
                                  _videoController?.play();
                                }
                              });
                            },
                            child: Icon(
                              _videoController?.value.isPlaying == true ? Icons.pause : Icons.play_arrow,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ],
                    )
                  : const Center(child: CircularProgressIndicator()),
            )
          else if (widget.story.imagePath != null && localFileExists(widget.story.imagePath!))
            Expanded(
              child: Image(
                image: localFileImage(widget.story.imagePath!)!,
                fit: BoxFit.cover,
              ),
            )
          else if (widget.story.imageUrl != null)
            Expanded(
              child: Image.network(
                widget.story.imageUrl!,
                fit: BoxFit.cover,
                errorBuilder: (context, error, stackTrace) {
                  return const Center(
                    child: Icon(Icons.broken_image, color: Colors.white24, size: 64),
                  );
                },
              ),
            )
          else
            const Expanded(
              child: Center(
                child: Icon(Icons.photo, color: Colors.white24, size: 64),
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.story.title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Colors.white)),
                const SizedBox(height: 8),
                Text('Опубліковано ${widget.story.createdAt.day}.${widget.story.createdAt.month}.${widget.story.createdAt.year}',
                    style: const TextStyle(color: Colors.white70)),
                if (widget.story.isVideo) ...[
                  const SizedBox(height: 8),
                  const Text('Відео історія', style: TextStyle(color: Colors.white70)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
