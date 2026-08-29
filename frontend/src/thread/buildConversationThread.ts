import type { ConversationThreadViewModel, TaskRunViewModel } from './types'

export function buildConversationThread(
  runs: TaskRunViewModel[],
  conversationId?: string,
): ConversationThreadViewModel {
  return { conversationId, runs: [...runs] }
}
